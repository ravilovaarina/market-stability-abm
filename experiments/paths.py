from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULTS_ROOT = PROJECT_ROOT / "results"


def add_project_root() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def result_path(section: str, kind: str, filename: str) -> Path:
    path = RESULTS_ROOT / section / kind
    path.mkdir(parents=True, exist_ok=True)
    return path / filename
