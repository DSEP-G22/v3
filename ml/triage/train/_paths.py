"""Import-path bootstrap for the training scripts.

The training scripts run as plain scripts (`python TriageModel/train/train_triage.py`), so the
schema and the MVP's reusable stages have to be put on `sys.path` before anything imports
them. Importing this module first is what makes `from schema import ...` work.
"""

from __future__ import annotations

import sys
from pathlib import Path

TRIAGE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = TRIAGE_ROOT.parent

# Order matters. `MVP/api` also contains a module named `schema` -- the thin re-export shim --
# and importing that one instead of the real definition would give two different class
# objects for the same model, so pydantic validation across the two would fail. TriageModel
# goes first, and the MVP path is appended rather than prepended.
for path in (TRIAGE_ROOT / "extract", TRIAGE_ROOT):
    entry = str(path)
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)

mvp_api = str(REPO_ROOT / "MVP" / "api")
if mvp_api not in sys.path:
    sys.path.append(mvp_api)
