from __future__ import annotations

import os
import sys
from pathlib import Path

# Renderやローカルでこのファイルを直接実行すると、sys.path[0]は
# gui/yura-body-pose-labになる。リポジトリ直下のappを確実にimportできるよう、
# プロジェクトルートを先に探索対象へ追加する。
PROJECT_ROOT = Path(__file__).resolve().parents[2]
project_root_text = str(PROJECT_ROOT)
if project_root_text not in sys.path:
    sys.path.insert(0, project_root_text)

import server as lab_server  # noqa: E402
from app.runtime.body_pose_3d_projector import (  # noqa: E402
    KinematicProceduralBodyController,
)


def main() -> None:
    lab_server.ProceduralBodyController = KinematicProceduralBodyController
    lab_server.HUB = lab_server.BodyPoseLabHub(
        tick_hz=float(os.getenv("YURA_BODY_POSE_LAB_TICK_HZ", "30"))
    )
    lab_server.main()


if __name__ == "__main__":
    main()
