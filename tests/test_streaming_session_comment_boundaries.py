from pathlib import Path


def test_streaming_subsystem_has_no_forbidden_core_imports() -> None:
    root = Path("subsystems/streaming")
    source = "\n".join(path.read_text() for path in root.rglob("*.py"))
    forbidden = (
        ".".join(("app", "plugins", "youtube_streaming")),
        ".".join(("app", "adapters", "streaming")),
        "app.runtime",
        "app.bootstrap",
        "AgentEvent",
        "ActivityTurnResult",
        "gui.",
        "subsystems.games",
    )
    assert [value for value in forbidden if value in source] == []


def test_sdk_imports_are_confined_to_adapters() -> None:
    root = Path("subsystems/streaming")
    offenders = []
    for path in root.rglob("*.py"):
        if "adapters" in path.parts:
            continue
        text = path.read_text()
        if "googleapiclient" in text or "obsws_python" in text:
            offenders.append(str(path))
    assert offenders == []
