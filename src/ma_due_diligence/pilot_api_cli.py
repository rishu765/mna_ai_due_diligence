"""Launch the authenticated pilot web application."""

from __future__ import annotations

import uvicorn

from ma_due_diligence.api.pilot_runtime import PilotApplicationRuntime


def main() -> None:
    runtime = PilotApplicationRuntime()
    try:
        uvicorn.run(runtime.app, host="127.0.0.1", port=8000)
    finally:
        runtime.close()


if __name__ == "__main__":
    main()
