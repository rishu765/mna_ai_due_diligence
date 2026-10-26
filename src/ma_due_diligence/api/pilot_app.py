"""Authenticated, deal-isolated FastAPI boundary for the controlled pilot."""

import os
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ma_due_diligence.domain import ReviewActionType
from ma_due_diligence.financial.methodology import engagement_methodology_payload
from ma_due_diligence.persistence import PilotAuditEvent, PilotDatabase, PilotDealRecord
from ma_due_diligence.security import (
    AuthenticationError,
    AuthorizationError,
    AuthPrincipal,
    LoginThrottle,
    Permission,
    PilotHttpSecurityPolicy,
)
from ma_due_diligence.security.service import PilotAuthService
from ma_due_diligence.workflow_final import HumanReviewSubmission, ReviewDecision
from ma_due_diligence.workflow_final.models import WorkflowState, WorkflowStatus

from .pilot_ai import (
    AiBudgetError,
    AiOutputValidationError,
    AiPolicyError,
    AiProviderError,
    ControlledAiDraftService,
)
from .pilot_documents import (
    PilotDocumentProcessingService,
    UploadRejectedError,
    document_payload,
)
from .pilot_exports import GeneratedExport, build_reviewed_report_pdf, build_reviewed_workbook
from .pilot_runs import PilotRunService, review_history_payload, run_payload
from .pilot_schemas import (
    AssignDealRoleRequest,
    CreatePilotDealRequest,
    DealMembershipResponse,
    PilotDealResponse,
    PilotDocumentBatchResponse,
    PilotDocumentResponse,
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
    documents: PilotDocumentProcessingService | None = None
    ai: ControlledAiDraftService | None = None
    http_security: PilotHttpSecurityPolicy = field(default_factory=PilotHttpSecurityPolicy)


def create_pilot_app(context: PilotApiContext) -> FastAPI:
    app = FastAPI(
        title="M&A Due-Diligence Pilot API",
        version="1.1.0-pilot",
        description="Authenticated and deal-isolated pilot boundary.",
    )
    throttle = LoginThrottle(context.http_security)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=list(context.http_security.allowed_hosts),
    )

    @app.middleware("http")
    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/pilot/"):
            response.headers["Cache-Control"] = "no-store"
        return response

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

    @app.get("/ready")
    def readiness() -> dict[str, str]:
        try:
            ready = context.database.integrity_check()
        except Exception as error:
            raise HTTPException(status_code=503, detail="service is not ready") from error
        if not ready:
            raise HTTPException(status_code=503, detail="service is not ready")
        return {"status": "ready", "database": "ok"}

    @app.get("/version")
    def version() -> dict[str, str]:
        return {
            "environment": os.environ.get("MADD_ENVIRONMENT", "local"),
            "release": os.environ.get("MADD_RELEASE_SHA", "development"),
        }

    @app.get("/", include_in_schema=False)
    def pilot_interface() -> FileResponse:
        return FileResponse(web_root / "index.html")

    @app.post("/pilot/auth/login", response_model=PilotLoginResponse)
    def login(payload: PilotLoginRequest, request: Request) -> dict[str, object]:
        client_host = "unknown" if request.client is None else request.client.host
        throttle_key = throttle.key(payload.email, client_host)
        retry_after = throttle.retry_after(throttle_key)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="login temporarily unavailable",
                headers={"Retry-After": str(retry_after)},
            )
        try:
            session = context.auth.login(email=payload.email, password=payload.password)
        except AuthenticationError as error:
            throttle.record_failure(throttle_key)
            raise _unauthorized("invalid email or password") from error
        throttle.reset(throttle_key)
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

    @app.get("/pilot/deals/{deal_id}/financial-methodology")
    def get_financial_methodology(
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
        return engagement_methodology_payload(
            reporting_currency=deal.reporting_currency,
            unit=deal.unit,
            as_of_date=deal.as_of_date.isoformat(),
            materiality_threshold=deal.materiality_threshold,
        )

    @app.get("/pilot/deals/{deal_id}/ai-policy")
    def get_ai_policy(
        deal_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        if context.database.get_deal(deal_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="deal not found")
        if context.ai is None:
            return {"enabled": False, "human_approval_required": True}
        return context.ai.policy.payload()

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

    @app.get(
        "/pilot/deals/{deal_id}/documents",
        response_model=list[PilotDocumentResponse],
    )
    def list_documents(
        deal_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> list[dict[str, object]]:
        documents = _documents_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        return [document_payload(item) for item in documents.list_documents(deal_id)]

    @app.post(
        "/pilot/deals/{deal_id}/documents",
        response_model=PilotDocumentResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_document(
        deal_id: str,
        request: Request,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
        filename: Annotated[str, Header(alias="X-Filename")],
        batch_id: Annotated[str, Header(alias="X-Upload-Batch")],
    ) -> dict[str, object]:
        documents = _documents_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DOCUMENT_WRITE)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > documents.maximum_file_bytes:
                    raise HTTPException(status_code=413, detail="file exceeds the upload limit")
            except ValueError as error:
                raise HTTPException(status_code=400, detail="invalid content length") from error
        payload = bytearray()
        async for block in request.stream():
            payload.extend(block)
            if len(payload) > documents.maximum_file_bytes:
                raise HTTPException(status_code=413, detail="file exceeds the upload limit")
        try:
            record = documents.process_upload(
                deal_id=deal_id,
                encoded_filename=filename,
                content_type=request.headers.get("content-type", "application/octet-stream"),
                content=bytes(payload),
                actor_id=authenticated.user_id,
                batch_id=batch_id,
            )
        except UploadRejectedError as error:
            rejection_status = 409 if error.code == "duplicate_document" else 422
            raise HTTPException(
                status_code=rejection_status,
                detail={"code": error.code, "message": error.detail},
            ) from error
        return document_payload(record)

    @app.get(
        "/pilot/deals/{deal_id}/document-batches/{batch_id}",
        response_model=PilotDocumentBatchResponse,
    )
    def get_document_batch(
        deal_id: str,
        batch_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        documents = _documents_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            return documents.batch_payload(deal_id, batch_id)
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="deal not found"
            ) from error
        except UploadRejectedError as error:
            raise HTTPException(status_code=400, detail=error.detail) from error

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

    @app.post(
        "/pilot/deals/{deal_id}/runs/{run_id}/ai-drafts/findings/{finding_id}",
        status_code=status.HTTP_201_CREATED,
    )
    def create_ai_finding_draft(
        deal_id: str,
        run_id: str,
        finding_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        ai = _ai_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.FINDING_DRAFT)
            state = runs.state(deal_id=deal_id, run_id=run_id)
            draft = ai.create_finding_draft(
                deal_id=deal_id,
                run_id=run_id,
                finding_id=finding_id,
                actor_id=authenticated.user_id,
                state=state,
            )
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        except AiBudgetError as error:
            raise HTTPException(
                status_code=429,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except AiPolicyError as error:
            raise HTTPException(
                status_code=409,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except AiOutputValidationError as error:
            raise HTTPException(
                status_code=422,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except AiProviderError as error:
            raise HTTPException(
                status_code=502,
                detail={"code": error.code, "message": str(error)},
            ) from error
        return draft.payload(ai.policy)

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
            _validate_complete_review(existing, payload)
            ai_draft_ids: dict[tuple[str, str], str] = {}
            for item in payload.decisions:
                if item.ai_draft_id is None:
                    continue
                if item.subject_type != "finding":
                    raise ValueError("AI drafts may be attached only to finding decisions")
                ai = _ai_or_503(context)
                ai.validate_reference(
                    deal_id=deal_id,
                    run_id=run_id,
                    finding_id=item.subject_id,
                    draft_id=item.ai_draft_id,
                )
                ai_draft_ids[(item.subject_type, item.subject_id)] = item.ai_draft_id
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
                actor_id=authenticated.user_id,
                submission=HumanReviewSubmission(
                    authenticated.display_name,
                    payload.rationale,
                    decisions,
                    datetime.now(UTC),
                ),
                ai_draft_ids=ai_draft_ids,
            )
        except AuthorizationError as error:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="access denied"
            ) from error
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        except AiPolicyError as error:
            raise HTTPException(
                status_code=400,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return run_payload(run_id, state)

    @app.get("/pilot/deals/{deal_id}/runs/{run_id}/review-history")
    def get_review_history(
        deal_id: str,
        run_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> dict[str, object]:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            events = runs.review_history(deal_id=deal_id, run_id=run_id)
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        return review_history_payload(events)

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

    @app.get("/pilot/deals/{deal_id}/runs/{run_id}/exports/report.pdf")
    def export_report_pdf(
        deal_id: str,
        run_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> Response:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            deal = context.database.get_deal(deal_id)
            if deal is None:
                raise KeyError(f"deal not found: {deal_id}")
            state = runs.state(deal_id=deal_id, run_id=run_id)
            generated = build_reviewed_report_pdf(
                deal,
                state,
                runs.review_history(deal_id=deal_id, run_id=run_id),
            )
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _record_export(context.database, deal_id, run_id, authenticated.user_id, generated)
        return _export_response(generated)

    @app.get("/pilot/deals/{deal_id}/runs/{run_id}/exports/workbook.xlsx")
    def export_workbook(
        deal_id: str,
        run_id: str,
        authenticated: Annotated[AuthPrincipal, Depends(principal)],
    ) -> Response:
        runs = _runs_or_503(context)
        try:
            context.auth.require_permission(authenticated, deal_id, Permission.DEAL_READ)
            deal = context.database.get_deal(deal_id)
            if deal is None:
                raise KeyError(f"deal not found: {deal_id}")
            state = runs.state(deal_id=deal_id, run_id=run_id)
            generated = build_reviewed_workbook(
                deal,
                state,
                runs.review_history(deal_id=deal_id, run_id=run_id),
            )
        except (AuthorizationError, KeyError) as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="run not found"
            ) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        _record_export(context.database, deal_id, run_id, authenticated.user_id, generated)
        return _export_response(generated)

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


def _validate_complete_review(
    state: WorkflowState,
    payload: PilotReviewSubmissionRequest,
) -> None:
    coordinator = state.get("specialist_result")
    request = state.get("review_request")
    if coordinator is None or request is None:
        raise ValueError("review context is unavailable")
    subjects = [(item.subject_type, item.subject_id) for item in payload.decisions]
    if len(subjects) != len(set(subjects)):
        raise ValueError("each review subject may be decided only once")
    if any(subject_type not in {"finding", "conflict"} for subject_type, _ in subjects):
        raise ValueError("review decisions support findings and required conflicts only")
    finding_actions = {
        ReviewActionType.APPROVE_FINDING,
        ReviewActionType.REJECT_FINDING,
        ReviewActionType.CHANGE_SEVERITY,
        ReviewActionType.MARK_NONMATERIAL,
        ReviewActionType.REQUEST_MORE_EVIDENCE,
    }
    for item in payload.decisions:
        if item.subject_type == "finding" and item.action not in finding_actions:
            raise ValueError(f"action {item.action.value} is invalid for a finding")
        if item.subject_type == "conflict" and item.action is not ReviewActionType.RESOLVE_CONFLICT:
            raise ValueError("conflicts may only be resolved")
    expected_findings = {item.finding.finding_id for item in coordinator.findings}
    submitted_findings = {
        subject_id for subject_type, subject_id in subjects if subject_type == "finding"
    }
    if submitted_findings != expected_findings:
        missing = sorted(expected_findings - submitted_findings)
        unexpected = sorted(submitted_findings - expected_findings)
        raise ValueError(
            f"every released finding requires one decision; missing={missing}, unexpected={unexpected}"
        )
    expected_conflicts = set(request.conflict_ids)
    submitted_conflicts = {
        subject_id for subject_type, subject_id in subjects if subject_type == "conflict"
    }
    if submitted_conflicts != expected_conflicts:
        missing = sorted(expected_conflicts - submitted_conflicts)
        unexpected = sorted(submitted_conflicts - expected_conflicts)
        raise ValueError(
            f"every required conflict requires one resolution; missing={missing}, unexpected={unexpected}"
        )


def _runs_or_503(context: PilotApiContext) -> PilotRunService:
    if context.runs is None:
        raise HTTPException(status_code=503, detail="workflow service is not configured")
    return context.runs


def _documents_or_503(context: PilotApiContext) -> PilotDocumentProcessingService:
    if context.documents is None:
        raise HTTPException(status_code=503, detail="document service is not configured")
    return context.documents


def _ai_or_503(context: PilotApiContext) -> ControlledAiDraftService:
    if context.ai is None:
        raise HTTPException(status_code=503, detail="controlled AI drafting is not configured")
    return context.ai


def _record_export(
    database: PilotDatabase,
    deal_id: str,
    run_id: str,
    actor_id: str,
    generated: GeneratedExport,
) -> None:
    database.append_audit_event(
        PilotAuditEvent(
            event_id=f"audit-{uuid4().hex}",
            deal_id=deal_id,
            actor_id=actor_id,
            action="report_exported"
            if generated.media_type == "application/pdf"
            else "workbook_exported",
            object_type="run",
            object_id=run_id,
            detail={
                "filename": generated.filename,
                "media_type": generated.media_type,
                "size_bytes": len(generated.content),
                "sha256": generated.sha256,
            },
            occurred_at=datetime.now(UTC),
        )
    )


def _export_response(generated: GeneratedExport) -> Response:
    return Response(
        content=generated.content,
        media_type=generated.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{generated.filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Export-SHA256": generated.sha256,
        },
    )
