"""Ensure the project root is importable so tests can `import models` etc.

The application modules use flat top-level imports (e.g. ``from models import X``),
so the project root must be on ``sys.path``. Placing this conftest at the root makes
pytest add the rootdir to ``sys.path`` (rootdir insertion) for all test sessions.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
