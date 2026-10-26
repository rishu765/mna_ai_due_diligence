"""HTTP hardening and bounded login throttling for the controlled pilot."""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PilotHttpSecurityPolicy:
    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "testserver")
    login_attempt_limit: int = 5
    login_window_seconds: int = 300
    login_block_seconds: int = 900

    def __post_init__(self) -> None:
        if not self.allowed_hosts or any(not host.strip() for host in self.allowed_hosts):
            raise ValueError("at least one nonblank allowed host is required")
        if self.login_attempt_limit <= 0:
            raise ValueError("login attempt limit must be positive")
        if self.login_window_seconds <= 0 or self.login_block_seconds <= 0:
            raise ValueError("login timing limits must be positive")


@dataclass(slots=True)
class _AttemptState:
    failures: list[float]
    blocked_until: float = 0.0


class LoginThrottle:
    """Process-local fixed-window protection without retaining raw user identifiers."""

    def __init__(self, policy: PilotHttpSecurityPolicy) -> None:
        self._policy = policy
        self._states: dict[str, _AttemptState] = {}
        self._lock = threading.Lock()

    def key(self, email: str, client_host: str) -> str:
        normalized = f"{email.strip().casefold()}\x00{client_host.strip().casefold()}"
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def retry_after(self, key: str, *, now: float | None = None) -> int | None:
        current = time.monotonic() if now is None else now
        with self._lock:
            state = self._states.get(key)
            if state is None or state.blocked_until <= current:
                return None
            return max(1, int(state.blocked_until - current + 0.999))

    def record_failure(self, key: str, *, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        cutoff = current - self._policy.login_window_seconds
        with self._lock:
            state = self._states.setdefault(key, _AttemptState([]))
            state.failures = [value for value in state.failures if value > cutoff]
            state.failures.append(current)
            if len(state.failures) >= self._policy.login_attempt_limit:
                state.blocked_until = current + self._policy.login_block_seconds

    def reset(self, key: str) -> None:
        with self._lock:
            self._states.pop(key, None)


def http_security_policy_from_environment() -> PilotHttpSecurityPolicy:
    hosts = tuple(
        host.strip()
        for host in os.environ.get("MADD_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(
            ","
        )
        if host.strip()
    )
    return PilotHttpSecurityPolicy(
        allowed_hosts=hosts,
        login_attempt_limit=_positive_integer("MADD_LOGIN_ATTEMPT_LIMIT", 5),
        login_window_seconds=_positive_integer("MADD_LOGIN_WINDOW_SECONDS", 300),
        login_block_seconds=_positive_integer("MADD_LOGIN_BLOCK_SECONDS", 900),
    )


def _positive_integer(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise RuntimeError(f"{name} must be an integer") from error
    if value <= 0:
        raise RuntimeError(f"{name} must be positive")
    return value
