"""Launch the authenticated pilot web application."""

from __future__ import annotations

import os

import uvicorn

from ma_due_diligence.api.pilot_runtime import PilotApplicationRuntime


def main() -> None:
    runtime = PilotApplicationRuntime()
    try:
        uvicorn.run(
            runtime.app,
            host=os.environ.get("MADD_BIND_HOST", "127.0.0.1"),
            port=_port_from_environment(),
            proxy_headers=True,
            forwarded_allow_ips=os.environ.get("MADD_FORWARDED_ALLOW_IPS", "127.0.0.1"),
            server_header=False,
        )
    finally:
        runtime.close()


def _port_from_environment() -> int:
    raw = os.environ.get("MADD_PORT", "8000")
    try:
        port = int(raw)
    except ValueError as error:
        raise RuntimeError("MADD_PORT must be an integer") from error
    if not 1 <= port <= 65535:
        raise RuntimeError("MADD_PORT must be between 1 and 65535")
    return port


if __name__ == "__main__":
    main()
