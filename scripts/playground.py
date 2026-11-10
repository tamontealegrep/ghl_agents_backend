"""Browser playground to test an agent by hand: chat, input variables, flow variables, LLM and tool calls.

Run it from ``backend/``::

    python scripts/playground.py                       # http://127.0.0.1:8765
    python scripts/playground.py --company babynova --open

It is the web version of ``scripts/agent_chat_tui.py`` (same harness): the agent's real LangGraph graph runs in this
process with real OpenAI calls, and tool calls are answered by the company's own backend app, so they hit the real
services configured in ``companies/<company>/.env`` (GoHighLevel, Google, Gmail). Booking something in a test
conversation changes the real calendar.

Needs the optional dependencies: ``pip install -e ".[tui]"``.
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Reads the command line.

    Args:
        argv: Arguments; defaults to ``sys.argv[1:]``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Browser playground for the agents.")
    parser.add_argument("--host", default="127.0.0.1", help="Interface to bind (default: localhost only).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--company", help="List only this company's agents.")
    parser.add_argument("--open", action="store_true", help="Open the page in the default browser.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Starts the playground server.

    Args:
        argv: Arguments; defaults to ``sys.argv[1:]``.
    """
    import uvicorn
    from playground.server import create_app

    args = parse_args(argv)
    url = f"http://{args.host}:{args.port}"
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Playground at {url}  (Ctrl+C to stop)")
    uvicorn.run(create_app(only_company=args.company), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
