"""
Shared pytest fixtures and sys.path bootstrap.

The unit tests import from the project root (`main.py`, `utils.*`,
`scripts.python.*`). On a fresh checkout, the working directory when
pytest is invoked is already the project root, so `main` and `utils`
are importable -- but `scripts/python/` is a directory containing a
hyphen-free module name (`scripts.python`). Python doesn't auto-add
that to sys.path, so we insert the project root explicitly here.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
