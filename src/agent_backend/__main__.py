"""Entry point: ``python -m agent_backend`` starts the server."""

from __future__ import annotations

import logging

import uvicorn

from agent_backend.settings import get_settings


def main() -> None:
    """Configures logging and runs the server until interrupted."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = get_settings()
    uvicorn.run("agent_backend.app:create_app", factory=True, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
