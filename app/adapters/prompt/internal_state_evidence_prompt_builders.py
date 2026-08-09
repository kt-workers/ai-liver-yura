from __future__ import annotations

import json
from typing import Any

from app.adapters.prompt.directive_aware_prompt_builders import (
    CharacterPromptBuilder as DirectiveAwareCharacterPromptBuilder,
    ResponseValidatorPromptBuilder as DirectiveAwareResponseValidatorPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import CharacterResponse, Claim, ResponseContext


class CharacterPromptBuilder(DirectiveAwareCharacterPromptBuilder):
    """内部状態への直接質問で、typed targetに直結する現在evidenceを明示する。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        prompt = super().build(
            context,
            character_profile=character_profile,
            correction=correction,
        )
        evidence = _target_specific_internal_state_evidence(context)
        if evidence is None:
            return prompt
        return "\n".join(
            [
                prompt,
                "# Target-specific Internal State Evidence",
                json.dumps(evidence, ensure_ascii=False, default=str),
                "target_evidenceはtyped targetについて現在値を判断するためにCoreが選択した"
                "直接evidenceである。targetの存在・強さについては、このevidenceを"
                "current_emotion/current_drive全体より優先する。",
                "scope=exact_dimensionで数値evidenceがある場合、その値と矛盾するtargetの"
                "肯定・否定・強度表現を生成しない。特にvalue=0.0は、そのdimensionが現在"
                "活性しているという肯定の根拠にしてはならない。",
                "non_target_contextは話し方、勢い、関心の向きなどを自然に整える補助情報であり、"
                "target_evidenceを上書きしない。curiosity、engagement、energy等が高くても、"
                "それだけで別targetの存在・強さを肯定しない。",
                "evidence_available=falseの場合、別の内部状態からtargetを推測して断定しない。"
                "不足したevidenceの範囲を越えず、人物として自然に直接答える。",
                "target_evidenceのpath、key、数値、scope等の内部表現はユーザーへ読み上げない。",
            ]
        )


class ResponseValidatorPromptBuilder(DirectiveAwareResponseValidatorPromptBuilder):
    """Characterのtarget状態主張を、target固有evidenceと意味的に照合する。"""

    def build(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        *,
        extracted_claims: tuple[Claim, ...] = (),
    ) -> str:
        prompt = super().build(
            context,
            response,
            extracted_claims=extracted_claims,
        )
        evidence = _target_specific_internal_state_evidence(context)
        if evidence is None:
            return prompt
        return "\n".join(
            [
                prompt,
                "# Target-specific Internal State Truth Check",
                json.dumps(evidence, ensure_ascii=False, default=str),
                "まずCharacter Responseがtyped targetについて何を主張しているかを意味的に判断し、"
                "その主張をtarget_evidenceと照合する。文章が自然かどうかより事実整合性を優先する。",
                "scope=exact_dimensionの数値evidenceと、targetの肯定・否定・強度が矛盾する場合は"
                "accepted=falseにする。特にvalue=0.0なのにtargetが現在少しでも存在する、"
                "高い、肯定できるという意味を主張している場合はaccepted=falseにする。",
                "non_target_contextの高さを理由にtargetとの矛盾を許容しない。"
                "curiosity、engagement、energy等はjoy、anger等の代替事実ではない。",
                "evidence_available=falseの場合も、別状態をtargetの現在値へ代用した断定は"
                "accepted=falseにする。",
                "内部キー名や数値をユーザー向けに説明している回答も従来どおり拒否する。",
            ]
        )


def _target_specific_internal_state_evidence(
    context: ResponseContext,
) -> dict[str, object] | None:
    target = _typed_internal_state_target(context)
    if target is None:
        return None
    target_id = str(target["id"]).strip().casefold()
    candidate_keys = _candidate_dimension_keys(target_id)

    if target_id in {"current_feeling", "current_mood", "feeling", "mood"}:
        return {
            "target": target,
            "scope": "emotion_overview",
            "evidence_available": bool(context.emotion),
            "target_evidence": context.emotion,
            "non_target_context": {"drive": context.drive},
        }

    matches: list[dict[str, object]] = []
    _collect_matching_values(
        context.emotion,
        path="emotion",
        candidate_keys=candidate_keys,
        matches=matches,
    )
    _collect_matching_values(
        context.drive,
        path="drive",
        candidate_keys=candidate_keys,
        matches=matches,
    )
    _collect_matching_values(
        context.situation,
        path="situation",
        candidate_keys=candidate_keys,
        matches=matches,
    )

    if target_id in {"current_desire", "desire"}:
        raw_plan = context.memory.get("response_content_plan")
        if isinstance(raw_plan, dict):
            primary_desire = raw_plan.get("primary_desire")
            if primary_desire is not None and str(primary_desire).strip():
                matches.append(
                    {
                        "path": "memory.response_content_plan.primary_desire",
                        "key": "primary_desire",
                        "value": str(primary_desire).strip(),
                    }
                )

    return {
        "target": target,
        "scope": "exact_dimension" if matches else "unresolved_target",
        "evidence_available": bool(matches),
        "target_evidence": matches,
        "non_target_context": {
            "current_emotion": context.emotion,
            "current_drive": context.drive,
        },
    }


def _typed_internal_state_target(context: ResponseContext) -> dict[str, str] | None:
    envelope = context.constraints.get("_internal_directive")
    if not isinstance(envelope, dict):
        return None
    meaning = envelope.get("structured_input_meaning")
    if not isinstance(meaning, dict):
        return None
    target = meaning.get("target")
    if not isinstance(target, dict):
        return None
    target_type = str(target.get("type") or "").strip()
    target_id = str(target.get("id") or "").strip()
    if target_type.casefold() not in {"internal_state", "agent_internal_state"}:
        return None
    speech_act = str(meaning.get("input_speech_act") or "").strip().casefold()
    expected_response = str(meaning.get("expected_response") or "").strip().casefold()
    if speech_act != "question" and expected_response != "direct_answer":
        return None
    if not target_id:
        return None
    return {"type": target_type, "id": target_id}


def _candidate_dimension_keys(target_id: str) -> frozenset[str]:
    keys = {target_id}
    for prefix in ("current_", "agent_"):
        if target_id.startswith(prefix) and len(target_id) > len(prefix):
            keys.add(target_id[len(prefix) :])
    return frozenset(key.casefold() for key in keys if key)


def _collect_matching_values(
    value: object,
    *,
    path: str,
    candidate_keys: frozenset[str],
    matches: list[dict[str, object]],
) -> None:
    if not isinstance(value, dict):
        return
    for raw_key, item in value.items():
        key = str(raw_key)
        normalized = key.strip().casefold()
        item_path = f"{path}.{key}"
        if _matches_dimension_key(normalized, candidate_keys) and _is_scalar(item):
            matches.append({"path": item_path, "key": key, "value": item})
        if isinstance(item, dict):
            _collect_matching_values(
                item,
                path=item_path,
                candidate_keys=candidate_keys,
                matches=matches,
            )


def _matches_dimension_key(key: str, candidate_keys: frozenset[str]) -> bool:
    if key in candidate_keys:
        return True
    return any(key.endswith(f"_{candidate}") for candidate in candidate_keys)


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))
