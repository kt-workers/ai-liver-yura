import hashlib
from pathlib import Path

from app.operations.host_launcher import build_launch_environment


class FakeSecrets:
    def github_token(self) -> str:
        return "secret"


def test_launcher_injects_goal_identity_and_path_without_persisting_token(tmp_path: Path) -> None:
    operations = tmp_path / "docs" / "operations"
    operations.mkdir(parents=True)
    content = b"version: 3\ngeneration: 9\nmission"
    (operations / "loop_mission_goal.md").write_bytes(content)

    environment = build_launch_environment(tmp_path, FakeSecrets(), {"PATH": "/opt/homebrew/bin"})

    assert environment.values["PATH"] == "/opt/homebrew/bin"
    assert environment.values["CODEX_MISSION_GOAL_VERSION"] == "3"
    assert environment.values["CODEX_MISSION_GOAL_GENERATION"] == "9"
    assert environment.values["CODEX_MISSION_GOAL_SHA256"] == hashlib.sha256(content).hexdigest()
    assert environment.values["GH_TOKEN"] == "secret"
