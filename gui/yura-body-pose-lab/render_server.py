from __future__ import annotations

import os
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from gui.body_pose_lab.entrypoint import run_from_env


if __name__ == "__main__":
    os.environ.setdefault("YURA_BODY_POSE_LAB_HOST", "0.0.0.0")
    os.environ.setdefault("YURA_BODY_POSE_LAB_LOCAL_SIMULATION", "1")
    run_from_env()
