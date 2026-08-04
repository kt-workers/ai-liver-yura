from pathlib import Path


def _web_root() -> Path:
    return (
        Path(__file__).parents[1]
        / "gui"
        / "yura-avatar-runtime-lab"
        / "web"
    )


def test_legacy_segment_playback_script_is_removed() -> None:
    web_root = _web_root()

    assert not (web_root / "performance-playback.js").exists()
    index_html = (web_root / "index.html").read_text(encoding="utf-8")
    assert 'src="/performance-playback.js"' not in index_html


def test_body_runtime_motion_extension_is_loaded() -> None:
    web_root = _web_root()
    index_html = (web_root / "index.html").read_text(encoding="utf-8")
    script = (web_root / "body-runtime-motions.js").read_text(encoding="utf-8")

    assert 'src="/body-runtime-motions.js"' in index_html
    for motion_name in (
        "breathing",
        "micro_sway",
        "recoil",
        "open_outward",
        "straighten",
        "posture_open",
        "posture_closed",
        "posture_forward",
        "posture_withdrawn",
    ):
        assert f'case "{motion_name}"' in script
