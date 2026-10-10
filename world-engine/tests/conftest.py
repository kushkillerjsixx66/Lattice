from __future__ import annotations

import sys
from pathlib import Path

# The repository directory uses a hyphen for project naming, so expose its
# internal Python package directory explicitly during test collection.
ENGINE_ROOT = Path(__file__).resolve().parents[1]
if str(ENGINE_ROOT) not in sys.path:
    sys.path.insert(0, str(ENGINE_ROOT))
