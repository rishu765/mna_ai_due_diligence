"""Authenticated, deal-isolated FastAPI boundary for the controlled pilot."""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from ma_due_diligence.persistence import PilotDatabase, PilotDealRecord
from ma_due_diligence.security import (
    AuthenticationError,
    AuthorizationError,
    AuthPrincipal,
    Permission,
)
from ma_due_diligence.security.service import PilotAuthService

from .pilot_schemas import (
    AssignDealRoleRequest,
    CreatePilotDealRequest,
    DealMembershipResponse,
    PilotDealResponse,
    PilotLoginRequest,
    PilotLoginResponse,
    PilotPrincipalResponse,
)


@dataclass(frozen=True, slots=True)
class PilotApiContext:
    database: PilotDatabase
    auth: PilotAuthService


def create_pilot_app(context: PilotApiContext) -> FastAPI:
    app = FastAPI(
        title="M&A Due-Diligence Pilot API",
        version="1.1.0-pilot",
        description="Authenticated and deal-isolated pilot boundary.",
    )

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
