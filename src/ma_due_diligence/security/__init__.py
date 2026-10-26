"""Pilot authentication and authorization boundary."""

from .errors import AuthenticationError, AuthorizationError
from .hardening import (
    LoginThrottle,
    PilotHttpSecurityPolicy,
    http_security_policy_from_environment,
)
from .models import (
    AccessSession,
    AuthPrincipal,
    DealMembership,
    DealRole,
    Permission,
    PilotUser,
    SessionRecord,
    UserStatus,
)
from .passwords import PasswordManager

__all__ = [
    "AccessSession",
    "AuthPrincipal",
    "AuthenticationError",
    "AuthorizationError",
    "DealMembership",
    "DealRole",
    "LoginThrottle",
    "PasswordManager",
    "Permission",
    "PilotHttpSecurityPolicy",
    "PilotUser",
    "SessionRecord",
    "UserStatus",
    "http_security_policy_from_environment",
]
