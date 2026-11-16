"""Path setup so `import bridge` and `import tests.fakes` work whether
pytest is run from the repo root or from inside tests/ — same pattern as
Nexus Brain's own tests/_pathfix.py, kept separate since this is a
different package."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
