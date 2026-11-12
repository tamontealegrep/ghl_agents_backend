"""Entry point: ``python -m agent_backend`` starts the server."""

from __future__ import annotations

import logging

import uvicorn

from agent_backend.llm import load_llm_settings
from agent_backend.settings import get_settings


def main() -> None:
    """Configures logging and runs the server until interrupted."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # A deployment with no usable model provider must fail here, loudly, instead of starting and answering 500.
    try:
        llm = load_llm_settings()
    except (ValueError, RuntimeError) as exc:
        raise SystemExit(f"Cannot start: {exc}") from exc
    logging.getLogger(__name__).info(
        "LLM providers by priority: %s", ", ".join(f"{p.name} ({p.model})" for p in llm.providers)
    )
    settings = get_settings()
    uvicorn.run("agent_backend.app:create_app", factory=True, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
