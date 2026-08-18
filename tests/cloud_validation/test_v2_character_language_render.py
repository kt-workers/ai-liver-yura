from typing import cast

from cloud_validation.v2_character_language_gate import CharacterLanguageLabGate
from cloud_validation.v2_character_language_render import (
    _service,
    _workspace_html,
    create_app,
)


def test_render_runtime_is_wrapped_by_final_evidence_gate() -> None:
    assert isinstance(_service, CharacterLanguageLabGate)


def test_render_exposes_health_readiness_run_and_workspace_routes() -> None:
    app = create_app(_service)
    paths = {
        cast(str, getattr(route, "path"))
        for route in app.routes
        if hasattr(route, "path")
    }
    assert {"/", "/health", "/api/readiness", "/api/run"}.issubset(paths)


def test_workspace_explains_integrated_isolation_and_human_semantic_split() -> None:
    html = _workspace_html()
    assert "Integrated" in html
    assert "Isolation" in html
    assert "Human Evaluation" in html
    assert "#363 semantic verification" in html
    assert "Export JSON" in html
    assert "Integratedは#363 ACCEPTED後もHuman評価が必要" in html
    assert "Isolation only / release evidenceには使用不可" in html
