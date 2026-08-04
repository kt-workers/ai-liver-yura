from pathlib import Path


def test_legacy_segment_playback_script_is_removed() -> None:
    web_root = (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )

    assert not (web_root / "performance-playback.js").exists()
    index_html = (web_root / "index.html").read_text(encoding="utf-8")
    assert 'src="/performance-playback.js"' not in index_html
