from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from app.adapters.llm.openai_responses import (
    OpenAIResponsesAdapter,
    OpenAIResponsesModelPolicy,
)
from app.domain.llm import (
    LLMModelClass,
    LLMReasoningEffort,
    LLMRoleRequest,
    LLMRoleResult,
)
from cloud_validation import v2_semantic_verification_lab as lab
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS
from cloud_validation.v2_semantic_verification_preset_overrides import PRESET_OVERRIDES

_ROOT = Path(__file__).parent
_SYNTHETIC_TIMELINE_MARGIN = timedelta(milliseconds=100)
_BASE_BUILD_VALIDATION_FIXTURE = lab.build_validation_fixture


def _gpt56_model_policy(model: str) -> dict[LLMModelClass, OpenAIResponsesModelPolicy]:
    efforts = {
        LLMReasoningEffort.MINIMAL: "none",
        LLMReasoningEffort.LOW: "low",
        LLMReasoningEffort.MEDIUM: "medium",
        LLMReasoningEffort.HIGH: "high",
    }
    return {
        model_class: OpenAIResponsesModelPolicy(model, efforts)
        for model_class in (
            LLMModelClass.FAST,
            LLMModelClass.BALANCED,
            LLMModelClass.DEEP_REASONING,
        )
    }


def _render_build_validation_fixture(
    request: lab.SemanticVerificationLabRequest,
    *,
    now: datetime | None = None,
) -> lab.LabFixture:
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None or reference.utcoffset() is None:
        raise ValueError("now はtimezone-awareでなければなりません")
    return _BASE_BUILD_VALIDATION_FIXTURE(
        request,
        now=reference - _SYNTHETIC_TIMELINE_MARGIN,
    )


def _load_preset_display() -> dict[str, dict[str, str]]:
    raw_value: object = json.loads(
        _ROOT.joinpath("v2_semantic_verification_presets_ja.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(raw_value, dict):
        raise RuntimeError("preset display metadata must be an object")
    value = cast(dict[object, object], raw_value)
    result: dict[str, dict[str, str]] = {}
    for preset_id, metadata_value in value.items():
        if not isinstance(preset_id, str) or not isinstance(metadata_value, dict):
            raise RuntimeError("preset display metadata is invalid")
        metadata = cast(dict[object, object], metadata_value)
        label = metadata.get("label")
        description = metadata.get("description")
        if not isinstance(label, str) or not label.strip():
            raise RuntimeError("preset label is invalid")
        if not isinstance(description, str) or not description.strip():
            raise RuntimeError("preset description is invalid")
        result[preset_id] = {"label": label, "description": description}
    return result


def _workspace_html() -> str:
    html = _ROOT.joinpath("v2_semantic_verification_workspace.html").read_text(
        encoding="utf-8"
    )
    style = _ROOT.joinpath("v2_semantic_verification_workspace.css").read_text(
        encoding="utf-8"
    )
    script = _ROOT.joinpath("v2_semantic_verification_workspace.js").read_text(
        encoding="utf-8"
    )
    return (
        html.replace("__WORKSPACE_STYLE__", style)
        .replace("__WORKSPACE_SCRIPT__", script)
        .replace(
            "__PRESET_DISPLAY__",
            json.dumps(_PRESET_DISPLAY, ensure_ascii=False),
        )
    )


class _RecordingPort:
    def __init__(self, settings: lab.LabSettings) -> None:
        self._settings = settings
        self._inner: OpenAIResponsesAdapter | None = None
        self.results: list[LLMRoleResult] = []

    def reset(self) -> None:
        self.results.clear()

    async def invoke(self, request: LLMRoleRequest) -> LLMRoleResult:
        if self._inner is None:
            self._inner = OpenAIResponsesAdapter.from_environment(
                lab._role_configs(self._settings)
            )
        result = await self._inner.invoke(request)
        self.results.append(result)
        return result


class _DiagnosticLabService(lab.SemanticVerificationLabService):
    def __init__(self, settings: lab.LabSettings) -> None:
        self._recording_port = _RecordingPort(settings)
        super().__init__(settings, self._recording_port)

    async def verify(
        self,
        request: lab.SemanticVerificationLabRequest,
    ) -> dict[str, object]:
        self._recording_port.reset()
        result = await super().verify(request)
        if not bool(result.get("ok")):
            result["provider_results"] = [
                item.to_dict() for item in self._recording_port.results
            ]
        return result


_PRESET_DISPLAY = _load_preset_display()
lab._model_policy = _gpt56_model_policy
lab._PRESETS.update(EXTRA_PRESETS)
lab._PRESETS.update(PRESET_OVERRIDES)
lab.build_validation_fixture = _render_build_validation_fixture
if set(lab._PRESETS) != set(_PRESET_DISPLAY):
    raise RuntimeError("all Render presets must have display metadata")
lab._INDEX_HTML = _workspace_html()
service = _DiagnosticLabService(lab.settings)
app = lab.create_app(settings=lab.settings, service=service)

__all__ = ["app"]
