from __future__ import annotations

import os

import server as lab_server
from app.runtime.body_pose_3d_projector import KinematicProceduralBodyController


def main() -> None:
    lab_server.ProceduralBodyController = KinematicProceduralBodyController
    lab_server.HUB = lab_server.BodyPoseLabHub(
        tick_hz=float(os.getenv("YURA_BODY_POSE_LAB_TICK_HZ", "30"))
    )
    lab_server.main()


if __name__ == "__main__":
    main()
