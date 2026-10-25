"""Authenticated, deal-isolated FastAPI boundary for the controlled pilot."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ma_due_diligence.persistence import PilotDatabase, PilotDealRecord
from ma_due_diligence.security import (
    AuthenticationError,
    AuthorizationError,
    AuthPrincipal,
    Permission,
)
from ma_due_diligence.security.service import PilotAuthService
from ma_due_diligence.workflow_final import HumanReviewSubmission, ReviewDecision
from ma_due_diligence.workflow_final.models import WorkflowStatus

from .pilot_runs import PilotRunService, run_payload
from .pilot_schemas import (
    AssignDealRoleRequest,
    CreatePilotDealRequest,
    DealMembershipResponse,
    PilotDealResponse,
    PilotLoginRequest,
    PilotLoginResponse,
    PilotPrincipalResponse,
    PilotReviewSubmissionRequest,
)
from .schemas import ReportResponse


@dataclass(frozen=True, slots=True)
class PilotApiContext:
    database: PilotDatabase
    auth: PilotAuthService
    runs: PilotRunService | None = None


def create_pilot_app(context: PilotApiContext) -> FastAPI:
    app = FastAPI(
        title="M&A Due-Diligence Pilot API",
        version="1.1.0-pilot",
        description="Authenticated and deal-isolated pilot boundary.",
    )
    web_root = Path(__file__).resolve().parents[1] / "web"
    app.mount("/assets", StaticFiles(directory=web_root), name="pilot-assets")

    def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
        if authorization is None:
            raise _unauthorized()
        scheme, separator, token = authorization.partition(" ")
        if separator != " " or scheme.casefold() != "bearer" or not token.strip():
            raise _unauthorized()
        return token.strip()

    def principal(token: Annotated[str, Depends(bearer_token)]) -> AuthPrincipal:
        try:
            return context.auth.authenticate(token)
        except AuthenticationError as error:
            raise _unauthorized() from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def pilot_interface() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.post("/pilot/auth/login", response_model=PilotLoginResponse)
    def login(payload: PilotLoginRequest) -> dict[str, object]:
        try:
            session = context.auth.login(email=payload.email, password=payload.password)
        except AuthenticationError as error:
            raise _unauthorized("invalid email or password") from error
        return {
            "access_token": session.token,
            "token_type": "bearer",
            "expires_at": session.expires_at,
            "user": asdict(session.principal),
        }

    @app.post("/pilot/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(
        token: Annotated[str, Depends(bearer_token)],
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> Response:
        del authenticated
        context.auth.logout(token)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/pilot/me", response_model=PilotPrincipalResponse)
    def me(authenticated: Annotated[AuthPrincipal, Depends(principal)]) -> dict[str, object]:
        return asdict(authenticated)

    @app.get("/pilot/deals", response_model=list[PilotDealResponse])
    def list_deals(
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> list[dict[str, object]]:
        return [_deal_payload(deal) for deal in context.auth.accessible_deals(authenticated)]

    @app.post(
        "/pilot/deals",
        response_model=PilotDealResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_deal(
        payload: CreatePilotDealRequest,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        if not authenticated.is_pilot_admin:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="access denied")
        now = datetime.now(UTC)
        try:
            deal = PilotDealRecord(
                deal_id=f"deal-{uuid4().hex}",
                name=payload.name,
                target_name=payload.target_name,
                buyer_name=payload.buyer_name,
                transaction_type=payload.transaction_type,
                reporting_currency=payload.reporting_currency,
                as_of_date=payload.as_of_date,
                materiality_threshold=payload.materiality_threshold,
                unit=payload.unit,
                workstreams=payload.workstreams,
                notes=payload.notes,
                created_by=authenticated.user_id,
                created_at=now,
                updated_at=now,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        context.database.create_deal(deal)
        return _deal_payload(deal)

    @app.get("/pilot/deals/{deal_id}", response_model=PilotDealResponse)
    def get_deal(
        deal_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        deal = context.database.get_deal(deal_id)
        if deal is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")
        return _deal_payload(deal)

    @app.put(
        "/pilot/deals/{deal_id}/memberships",
        response_model=DealMembershipResponse,
    )
    def assign_deal_role(
        deal_id: str,
        payload: AssignDealRoleRequest,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        try:
            membership = context.auth.assign_deal_role(
                actor=authenticated,
                deal_id=deal_id,
                user_id=payload.user_id,
                role=payload.role,
            )
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="access denied"
            ) from error
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="resource not found"
            ) from error
        return asdict(membership)

    @app.post("/pilot/deals/{deal_id}/runs", status_code=status.HTTP_201_CREATED)
    def start_run(
        deal_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.ANALYSIS_RUN)
            state = runs.start_demo_run(deal_id=deal_id, actor_id=authenticated.user_id)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        return run_payload(state["request"].run_id, state)

    @app.get("/pilot/deals/{deal_id}/runs/{run_id}")
    def get_run(
        deal_id: str,
        run_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            state = runs.state(deal_id=deal_id, run_id=run_id)
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        return run_payload(run_id, state)

    @app.post("/pilot/deals/{deal_id}/runs/{run_id}/review")
    def review_run(
        deal_id: str,
        run_id: str,
        payload: PilotReviewSubmissionRequest,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.REVIEW_DECIDE)
            existing = runs.state(deal_id=deal_id, run_id=run_id)
            if existing.get("status") is not WorkflowStatus.REVIEW_REQUIRED:
                raise HTTPException(status_code=409, detail="run is not awaiting review")
            decisions = tuple(
                ReviewDecision(
                    item.subject_type,
                    item.subject_id,
                    item.action,
                    item.rationale,
                    item.severity,
                    item.preferred_source_id,
                )
                for item in payload.decisions
            )
            state = runs.resume(
                deal_id=deal_id,
                run_id=run_id,
                submission=HumanReviewSubmission(
                    authenticated.display_name,
                    payload.rationale,
                    decisions,
                    datetime.now(UTC),
                ),
            )
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="access denied"
            ) from error
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run_payload(run_id, state)

    @app.get(
        "/pilot/deals/{deal_id}/runs/{run_id}/report",
        response_model=ReportResponse,
    )
    def get_report(
        deal_id: str,
        run_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            state = runs.state(deal_id=deal_id, run_id=run_id)
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        report = state.get("report")
        if report is None:
            raise HTTPException(status_code=409, detail="report is not available")
        return {"run_id": run_id, "status": state["status"], "report": report}

    return app


def _unauthorized(detail: str = "authentication required") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _deal_payload(deal: PilotDealRecord) -> dict[str, object]:
    return {
        "deal_id": deal.deal_id,
        "name": deal.name,
        "target_name": deal.target_name,
        "buyer_name": deal.buyer_name,
        "transaction_type": deal.transaction_type,
        "reporting_currency": deal.reporting_currency,
        "as_of_date": deal.as_of_date,
        "materiality_threshold": deal.materiality_threshold,
        "unit": deal.unit,
        "workstreams": deal.workstreams,
        "notes": deal.notes,
        "status": deal.status,
    }


def _runs_or_503(context: PilotApiContext) -> PilotRunService:
    if context.runs is None:
        raise HTTPException(status_code=503, detail="workflow service is not configured")
    return context.runs
