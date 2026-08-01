from pathlib import Path


def test_core_streaming_integration_has_no_concrete_or_sdk_imports() -> None:
    root = Path("app/integrations/streaming")
    source = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    forbidden = (
        "subsystems.streaming",
        ".".join(("app", "plugins", "youtube_streaming")),
        ".".join(("app", "adapters", "youtube")),
        ".".join(("app", "adapters", "obs")),
        ".".join(("app", "adapters", "streaming")),
        "googleapiclient",
        "google_auth",
        "obsws",
        "obswebsocket",
    )
    assert not [name for name in forbidden if name in source]


def test_core_main_uses_only_streaming_integration_boundary() -> None:
    source = Path("app/__main__.py").read_text(encoding="utf-8")
    assert "app.integrations.streaming" in source
    assert "subsystems.streaming" not in source
    assert ".".join(("app", "bootstrap", "streaming")) not in source
