"""
Hace importable el paquete family_aims al correr pytest desde cualquier cwd.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
