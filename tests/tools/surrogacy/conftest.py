"""Hace importable el paquete surrogacy al correr pytest desde cualquier cwd."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

