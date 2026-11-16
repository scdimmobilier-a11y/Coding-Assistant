"""
nexus_brain
=============

Bootstrap: makes `nexus_functor` (the provided, unmodified dependency) and
the `vendor/*` modules importable as soon as `nexus_brain` is imported,
without requiring the caller to manipulate `sys.path` themselves — mirrors
the same pattern used for `nexus_vendor` in the sibling Nexus Assistant
project. Degrades silently (adapters that need a given vendor module will
raise a clear ImportError themselves) if a path is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

_PATHS = [
    _ROOT,                                    # nexus_brain itself (if run from a copy)
    _ROOT / "nexus_functor",                  # the provided nexus_functor package
    _ROOT / "vendor" / "nexus_exec",          # nexus_exec.mini (Coordinator, MockWorker)
    _ROOT / "vendor" / "nexus_proactive_when",  # real DecisionEngine/SleepTimeCalculator
]

for _p in _PATHS:
    _s = str(_p)
    if _p.is_dir() and _s not in sys.path:
        sys.path.insert(0, _s)

__version__ = "1.0.0"