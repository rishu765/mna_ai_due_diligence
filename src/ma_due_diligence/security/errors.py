"""Stable authentication and authorization errors."""


class AuthenticationError(RuntimeError):
    pass


class AuthorizationError(RuntimeError):
    pass
