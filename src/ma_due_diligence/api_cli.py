"""Launch the local diligence API."""

import uvicorn


def main() -> None:
    uvicorn.run("ma_due_diligence.api.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
