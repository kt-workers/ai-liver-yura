from __future__ import annotations

from app.domain.speech_semantics import SpeechSemanticFactKind
from cloud_validation.v2_character_language_lab import (
    CharacterLanguageLabMode,
    CharacterLanguageLabProbe,
    CharacterLanguageLabRequest,
    CharacterLanguageLabStatus,
    _character_source,
    _committed_plan,
    _RecordingPort,
    _Scenario,
)
from cloud_validation.v2_character_language_same_plan import (
    StrictSamePlanCharacterLanguageLabService,
    _model_policy,
)


def _gratitude_turn(identifier: str, label: str) -> _Scenario:
    return _Scenario(
        identifier,
        label,
        SpeechSemanticFactKind.DISCOURSE,
        f"interaction-{identifier}",
        "communicative_act",
        {"kind": "gratitude", "target_ref": "user", "reason": label},
    )


_GRATITUDE_TURNS = tuple(
    _gratitude_turn(identifier, label)
    for identifier, label in (
        ("gratitude_help", "作業を手伝ってもらった"),
        ("gratitude_information", "情報を教えてもらった"),
        ("gratitude_wait", "待ってもらった"),
        ("gratitude_fix", "修正してもらった"),
        ("gratitude_confirmation", "結果を確認してもらった"),
    )
)


class CrossPlanConversationCharacterLanguageLabService(StrictSamePlanCharacterLanguageLabService):
    """別turn・別Plan・別contextのbaselineを観測する#434 probe。"""

    async def run(self, request: CharacterLanguageLabRequest) -> dict[str, object]:
        if request.probe is not CharacterLanguageLabProbe.CROSS_PLAN_CONVERSATION:
            return await super().run(request)
        if request.mode is not CharacterLanguageLabMode.ISOLATION:
            raise ValueError("Cross-Plan conversationはIsolation fixtureだけで実行します")
        if request.scenario_id != "gratitude":
            raise ValueError("Cross-Plan conversationのscenario_idはgratitudeでなければなりません")
        if request.repetitions != len(_GRATITUDE_TURNS):
            raise ValueError("Gratitude Cross-Plan conversationは5 turnで実行します")

        profile, source = _character_source(self._settings, request.mode)
        if profile is None:
            return {
                "ok": False,
                "status": CharacterLanguageLabStatus.BLOCKED_UPSTREAM_CHARACTER_DEFINITION.value,
                "mode": request.mode.value,
                "evidence_class": "not_eligible",
                "integrated_evidence_eligible": False,
                "character_source": source,
                "runs": [],
            }

        recorder = _RecordingPort(self._role_port(request))
        runs: list[dict[str, object]] = []
        for turn_index, scenario in enumerate(_GRATITUDE_TURNS):
            plan = await _committed_plan(scenario)
            run, _ = await self._run_once_same_plan(
                request, plan, profile, source, recorder, (), turn_index
            )
            run["conversation_turn"] = {
                "turn_index": turn_index + 1,
                "scenario_id": scenario.scenario_id,
                "context_summary": scenario.label,
            }
            runs.append(run)

        return {
            "ok": all(bool(item.get("ok")) for item in runs),
            "status": CharacterLanguageLabStatus.COMPLETED.value,
            "mode": request.mode.value,
            "probe": request.probe.value,
            "evidence_class": "isolation_only",
            "integrated_evidence_eligible": False,
            "scenario_set": "gratitude_conversation_v1",
            "character_source": source,
            "model_policy": _model_policy(request),
            "conversation": {
                "turns": len(_GRATITUDE_TURNS),
                "prior_realizations": "各turnは空。same-Plan専用provenance契約を越えない",
            },
            "runs": runs,
            "provider_metrics": recorder.metrics(),
            "branch": "test/v2-character-language-lab",
            "git_head": self._settings.git_head,
        }


__all__ = ["CrossPlanConversationCharacterLanguageLabService"]
