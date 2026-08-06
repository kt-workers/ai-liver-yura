from __future__ import annotations

from gui.body_pose_lab.composition import BodyPoseLabComposition
from gui.body_pose_lab.config import BodyPoseLabConfig


def run_from_env() -> None:
    config = BodyPoseLabConfig.from_env()
    components = BodyPoseLabComposition.create(config)
    host, port = components.http_server.address
    print(f"Body Pose Lab: http://{host}:{port}")
    print("終了: Ctrl-C")
    try:
        components.run()
    except KeyboardInterrupt:
        pass
