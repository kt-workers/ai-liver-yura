from __future__ import annotations

from cloud_validation.character_semantic_extended_batch import (
    _authorization_header,
    _select_presets,
    run_batch,
)


def _preset(label: str, user_input: str) -> dict[str, object]:
    return {
        "label": label,
        "data": {
            "user_input": user_input,
            "structured_input_meaning": {},
            "internal_directive": {},
            "emotion": {},
            "drive": {},
        },
    }


def test_authorization_header_uses_basic_auth() -> None:
    assert _authorization_header("user", "pass") == "Basic dXNlcjpwYXNz"


def test_select_presets_keeps_server_order_and_filters_extended_prefix() -> None:
    presets = {
        "joy_low": _preset("basic", "楽しい？"),
        "extended_e2": _preset("E2", "悲しい？"),
        "extended_e1": _preset("E1", "楽しい？"),
    }

    selected = _select_presets(presets, prefix="extended_")

    assert [item[0] for item in selected] == ["extended_e2", "extended_e1"]
    assert [item[1] for item in selected] == ["E2", "E1"]


def test_explicit_presets_follow_requested_order() -> None:
    presets = {
        "extended_e1": _preset("E1", "楽しい？"),
        "extended_e2": _preset("E2", "悲しい？"),
    }

    selected = _select_presets(
        presets,
        prefix="extended_",
        explicit_keys=("extended_e2", "extended_e1"),
    )

    assert [item[0] for item in selected] == ["extended_e2", "extended_e1"]


def test_run_batch_collects_all_cases_without_semantic_pass_fail_decision() -> None:
    calls: list[tuple[str, dict[str, object] | None]] = []
    responses = iter(
        [
            {"generation_result": {"status": "validated", "attempts": 1}},
            {"generation_result": {"status": "fallback", "attempts": 2}},
        ]
    )

    def requester(**kwargs):
        path = kwargs["path"]
        payload = kwargs["payload"]
        calls.append((path, payload))
        if path == "/health":
            return {"status": "ok", "mode": "live", "model_configured": True}
        if path == "/api/presets":
            return {
                "basic": _preset("Basic", "x"),
                "extended_e1": _preset("E1", "楽しい？"),
                "extended_e2": _preset("E2", "悲しい？"),
            }
        return next(responses)

    progress: list[str] = []
    result = run_batch(
        base_url="https://lab.example",
        username="user",
        password="pass",
        request_json=requester,
        progress=progress.append,
    )

    assert result["selected_preset_keys"] == ["extended_e1", "extended_e2"]
    assert result["transport_error_count"] == 0
    assert result["semantic_pass_fail_automatically_decided"] is False
    assert len(result["cases"]) == 2
    assert result["cases"][0]["result"]["generation_result"]["status"] == "validated"
    assert result["cases"][1]["result"]["generation_result"]["status"] == "fallback"
    assert [path for path, _ in calls] == [
        "/health",
        "/api/presets",
        "/api/character-response",
        "/api/character-response",
    ]
    assert all("PASS" not in line and "FAIL" not in line for line in progress)


def test_run_batch_continues_after_one_case_transport_error() -> None:
    post_count = 0

    def requester(**kwargs):
        nonlocal post_count
        path = kwargs["path"]
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/presets":
            return {
                "extended_e1": _preset("E1", "楽しい？"),
                "extended_e2": _preset("E2", "悲しい？"),
            }
        post_count += 1
        if post_count == 1:
            raise RuntimeError("temporary provider failure")
        return {"generation_result": {"status": "validated", "attempts": 1}}

    result = run_batch(
        base_url="https://lab.example/",
        username="user",
        password="pass",
        request_json=requester,
        progress=lambda _: None,
    )

    assert post_count == 2
    assert result["transport_error_count"] == 1
    first, second = result["cases"]
    assert first["runner_error"]["type"] == "RuntimeError"
    assert "result" not in first
    assert second["result"]["generation_result"]["status"] == "validated"


def test_run_batch_forces_prompts_off_by_default() -> None:
    seen_payload: dict[str, object] | None = None

    def requester(**kwargs):
        nonlocal seen_payload
        path = kwargs["path"]
        if path == "/health":
            return {"status": "ok"}
        if path == "/api/presets":
            preset = _preset("E1", "楽しい？")
            preset["data"]["include_prompts"] = True
            return {"extended_e1": preset}
        seen_payload = kwargs["payload"]
        return {"generation_result": {"status": "validated", "attempts": 1}}

    run_batch(
        base_url="https://lab.example",
        username="user",
        password="pass",
        request_json=requester,
        progress=lambda _: None,
    )

    assert seen_payload is not None
    assert seen_payload["include_prompts"] is False
