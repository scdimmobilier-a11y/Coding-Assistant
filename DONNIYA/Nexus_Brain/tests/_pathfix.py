"""Shared sys.path bootstrap for the test suite. Puts the project root on
sys.path (so `nexus_brain` itself is importable), then imports `nexus_brain`
once — its own `__init__.py` bootstrap takes care of `nexus_functor` and the
`vendor/*` modules. Import this module first (`import _pathfix`) at the top
of every test file."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import nexus_brain  # noqa: F401  — triggers the central sys.path bootstrap
