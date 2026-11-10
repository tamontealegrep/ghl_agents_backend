"""Paths, constants and the shared console of the terminal chat."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import devenv

try:
    import questionary
    from rich.console import Console
except ImportError as exc:  # pragma: no cover - only without the optional dependencies
    raise SystemExit(f"Missing dependency ({exc.name}). Install it with: pip install -e \".[tui]\"") from exc

BACKEND_ROOT = devenv.BACKEND_ROOT
COMPANIES_DIR = BACKEND_ROOT / "companies"
DEFAULT_SESSION_DIR = BACKEND_ROOT / "tui_sessions"
SESSIONS_DB = "sessions.db"

console = Console()

# Seeded into `history` (never spoken) so the very first `eval: "llm"` gate of an outbound-call agent has evidence to
# reason from; on a genuinely empty history that gate reliably falls back to "not answered" and the agent never speaks.
OUTBOUND_ANSWERED_SEED_LINE = "[system note] The outbound call has connected -- the contact answered and is on the line."

STYLE = questionary.Style([
    ("qmark", "fg:#00d7af bold"),
    ("question", "bold"),
    ("answer", "fg:#00d7af bold"),
    ("pointer", "fg:#00d7af bold"),
    ("highlighted", "fg:#00d7af bold"),
    ("selected", "fg:#00d7af bold"),
    ("separator", "fg:#6c6c6c"),
    ("instruction", "fg:#6c6c6c italic"),
])
