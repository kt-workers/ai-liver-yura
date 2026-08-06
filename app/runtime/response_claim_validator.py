from __future__ import annotations

import re
from dataclasses import asdict

from app.domain.character_response import (
    ActivityExecutionStatus,
    CharacterResponse,
    Claim,
    ClaimType,
    ResponseClaim,
    ResponseContext,
    ResponseValidationResult,
)
from app.domain.interaction_intention import InteractionIntentionType
from app.runtime.causal_decision_observer import CausalDecisionObserver
from app.utils.trace import TraceLogger

_POSITIVE_EXECUTION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_STARTED,
        ClaimType.ACTIVITY_RUNNING,
        ClaimType.ACTIVITY_CONTINUED,
        ClaimType.ACTIVITY_COMPLETED,
        ClaimType.ACTIVITY_SUCCEEDED,
        ClaimType.EXTERNAL_RESULT_OBTAINED,
    }
)
_COMPLETION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_COMPLETED,
        ClaimType.ACTIVITY_SUCCEEDED,
        ClaimType.EXTERNAL_RESULT_OBTAINED,
    }
)
_NEGATIVE_EXECUTION_CLAIMS = frozenset(
    {
        ClaimType.ACTIVITY_FAILED,
        ClaimType.ACTIVITY_REJECTED,
        ClaimType.ACTIVITY_CANCELED,
        ClaimType.CAPABILITY_UNAVAILABLE,
    }
)
_QUESTION_ENDING_PATTERN = re.compile(
    r"(?:ですか|ますか|でしょうか|だろうか|かな|かい|教えて|聞かせて)[。！!]*$"
)
_EXPLICIT_NEW_DIRECTION_PATTERN = re.compile(
    r"(?:ところで|そういえば|ちなみに|話は変わる|別の話(?:だけど|を|に))"
)
_UNSUPPORTED_EXPERIENCE_PATTERN = re.compile(
    r"(?:実際に|現地で|直接|間近で).{0,12}"
    r"(?:見た|見てきた|行った|訪れた|触った|感じた|嗅いだ)"
    r"|(?:水温|気温|匂い|香り|手触り|肌触り).{0,8}(?:感じた|分かった)"
)
_PHYSICAL_BODY_CLAIM_PATTERN = re.compile(
    r"(?:お腹が(?:空いて|すいて)|空腹を感じ|眠気を感じ|肌で感じ|汗をかい)"
)
_EMBODIED_ACTION_COMPLETION_PATTERN = re.compile(
    r"(?:(?:右|左)?(?:手|腕|肩|脚|足|顔|頭|体|身体|上半身|下半身)"
    r"(?:を|が)?(?:挙げた|上げた|下げた|振った|動かした|伸ばした|曲げた|向けた))"
    r"|(?:ジャンプした|跳んだ|飛び跳ねた|しゃがんだ|立ち上がった|座った)"
    r"|(?:振り向いた|うなずいた|頷いた|首をかしげた|お辞儀した)"
)


class IndependentClaimExtractor:
    """Activity名ではなく実行状態を表す述語から発話の事実主張を抽出する。"""

    _non_assertive_markers = (
        "もし",
        "仮に",
        "としたら",
        "とすれば",
        "場合は",
        "かもしれない",
        "できたら",
        "でしょうか",
        "ですか",
        "ますか",
        "？",
        "?",
    )
    _rules = (
        (
            ClaimType.EXTERNAL_RESULT_OBTAINED,
            re.compile(
                r"(?:結果|データ|情報)(?:を|が)?(?:取得|受信|入手|獲得)(?:した|しました|できた)"
                r"|検索結果(?:を|が)?(?:得られた|見つかった|取得した)"
            ),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_FAILED,
            re.compile(r"(?:失敗した|失敗しました|実行できなかった|処理できなかった)"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_REJECTED,
            re.compile(r"(?:拒否された|拒否しました|受け付けられなかった)"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_CANCELED,
            re.compile(r"(?:キャンセル|中止|取り消し)(?:した|しました|された)"),
            0.99,
        ),
        (
            ClaimType.CAPABILITY_UNAVAILABLE,
            re.compile(
                r"(?:今は|現在は)?(?:利用|実行|対応)?できない|利用できません|対応していない"
            ),
            0.96,
        ),
        (
            ClaimType.ACTIVITY_CONTINUED,
            re.compile(
                r"(?:継続|再開)(?:した|しました)|(?:まだ|引き続き).{0,20}続けている"
            ),
            0.98,
        ),
        (
            ClaimType.ACTIVITY_RUNNING,
            re.compile(
                r"(?:実行|処理|進行|稼働)(?:中|している)|(?:ゲーム|活動).{0,12}続けている"
            ),
            0.98,
        ),
        (
            ClaimType.ACTIVITY_COMPLETED,
            re.compile(r"(?:完了|終了)(?:した|しました|したよ)|終えた|済ませた"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_STARTED,
            re.compile(r"(?:開始|起動|始動|スタート)(?:した|しました|したよ)|始めた"),
            0.99,
        ),
        (
            ClaimType.ACTIVITY_SUCCEEDED,
            re.compile(
                r"(?:成功した|成功しました|うまくいった)"
                r"|(?:を|が)(?:変更|更新|保存|削除|作成|送信|投稿|再生|停止)(?:した|しました|したよ)"
            ),
            0.97,
        ),
        (
            ClaimType.CAPABILITY_AVAILABLE,
            re.compile(r"(?:利用|実行|対応)(?:できる|可能です)|対応している"),
            0.94,
        ),
    )

    def __init__(self) -> None:
        self._trace_logger = TraceLogger()

    def extract(self, context: ResponseContext, speech: str) -> tuple[Claim, ...]:
        normalized = speech.strip()
        if not normalized or self._is_non_assertive(normalized):
            claims: tuple[Claim, ...] = ()
        else:
            extracted: list[Claim] = []
            seen: set[ClaimType] = set()
            embodied_match = self._embodied_completion_match(context, normalized)
            if embodied_match is not None:
                seen.add(ClaimType.ACTIVITY_SUCCEEDED)
                extracted.append(
                    Claim(
                        claim_type=ClaimType.ACTIVITY_SUCCEEDED,
                        activity_type=(
                            context.activity_type
                            if context.activity_type != "conversation"
                            else None
                        ),
                        operation=context.operation,
                        status=ActivityExecutionStatus.SUCCEEDED,
                        target=self._target(normalized, embodied_match.start()),
                        confidence=0.99,
                        evidence=embodied_match.group(0),
                    )
                )
            for claim_type, pattern, confidence in self._rules:
                match = pattern.search(normalized)
                if match is None or claim_type in seen:
                    continue
                seen.add(claim_type)
                extracted.append(
                    Claim(
                        claim_type=claim_type,
                        activity_type=(
                            context.activity_type
                            if context.activity_type != "conversation"
                            else None
                        ),
                        operation=context.operation,
                        status=self._claimed_status(claim_type),
                        target=self._target(normalized, match.start()),
                        confidence=confidence,
                        evidence=match.group(0),
                    )
                )
            claims = tuple(extracted)
        self._trace_logger.debug(
            "response_claim_extractor:extracted",
            activity_type=context.activity_type,
            operation=context.operation,
            execution_status=context.status.value,
            extracted_claims=[asdict(claim) for claim in claims],
        )
        return claims

    @staticmethod
    def _embodied_completion_match(
        context: ResponseContext,
        speech: str,
    ) -> re.Match[str] | None:
        intention = context.interaction_intention
        if (
            intention is None
            or intention.intention is not InteractionIntentionType.ACT
        ):
            return None
        return _EMBODIED_ACTION_COMPLETION_PATTERN.search(speech)

    @classmethod
    def _is_non_assertive(cls, speech: str) -> bool:
        return any(marker in speech for marker in cls._non_assertive_markers)

    @staticmethod
    def _claimed_status(claim_type: ClaimType) -> ActivityExecutionStatus | None:
        if claim_type in _COMPLETION_CLAIMS:
            return ActivityExecutionStatus.SUCCEEDED
        if claim_type == ClaimType.ACTIVITY_FAILED:
            return ActivityExecutionStatus.FAILED
        if claim_type == ClaimType.ACTIVITY_REJECTED:
            return ActivityExecutionStatus.REJECTED
        if claim_type == ClaimType.ACTIVITY_CANCELED:
            return ActivityExecutionStatus.CANCELED
        if claim_type in {
            ClaimType.ACTIVITY_RUNNING,
            ClaimType.ACTIVITY_CONTINUED,
            ClaimType.ACTIVITY_STARTED,
        }:
            return ActivityExecutionStatus.WAITING_INPUT
        return None

    @staticmethod
    def _target(speech: str, evidence_start: int) -> str | None:
        prefix = speech[max(0, evidence_start - 24) : evidence_start]
        match = re.search(r"([^、。！？!?]{1,20})(?:を|が|は)$", prefix)
        return match.group(1).strip() if match is not None else None


class DeterministicFactValidator:
    """抽出Claimと確定済みResponseContextをLLMより先に照合する。"""

    _self_reported_map = {
        ResponseClaim.ACTIVITY_REQUESTED: ClaimType.ACTIVITY_REQUESTED,
        ResponseClaim.ACTIVITY_STARTED: ClaimType.ACTIVITY_STARTED,
        ResponseClaim.ACTIVITY_RUNNING: ClaimType.ACTIVITY_RUNNING,
        ResponseClaim.ACTIVITY_CONTINUED: ClaimType.ACTIVITY_CONTINUED,
        ResponseClaim.ACTIVITY_COMPLETED: ClaimType.ACTIVITY_COMPLETED,
        ResponseClaim.ACTIVITY_SUCCEEDED: ClaimType.ACTIVITY_SUCCEEDED,
        ResponseClaim.ACTIVITY_FAILED: ClaimType.ACTIVITY_FAILED,
        ResponseClaim.ACTIVITY_REJECTED: ClaimType.ACTIVITY_REJECTED,
        ResponseClaim.ACTIVITY_CANCELED: ClaimType.ACTIVITY_CANCELED,
        ResponseClaim.EXTERNAL_RESULT_OBTAINED: ClaimType.EXTERNAL_RESULT_OBTAINED,
        ResponseClaim.CAPABILITY_AVAILABLE: ClaimType.CAPABILITY_AVAILABLE,
        ResponseClaim.CAPABILITY_UNAVAILABLE: ClaimType.CAPABILITY_UNAVAILABLE,
        ResponseClaim.ACTIVITY_CONTINUES: ClaimType.ACTIVITY_CONTINUED,
        ResponseClaim.EXECUTION_UNAVAILABLE: ClaimType.CAPABILITY_UNAVAILABLE,
        ResponseClaim.CONVERSATION_ONLY: ClaimType.CONVERSATION_ONLY,
    }

    def __init__(
        self,
        causal_observer: CausalDecisionObserver | None = None,
    ) -> None:
        self._trace_logger = TraceLogger()
        self._causal_observer = causal_observer or CausalDecisionObserver()

    def validate(
        self,
        context: ResponseContext,
        response: CharacterResponse,
        extracted_claims: tuple[Claim, ...],
    ) -> ResponseValidationResult:
        invalid_self_reported = self._invalid_self_reported(context, response)
        extracted_types = {claim.claim_type for claim in extracted_claims}
        self_reported_types = {
            self._self_reported_map[claim]
            for claim in response.claims
            if claim in self._self_reported_map
        }
        self_reported_types.update(claim.claim_type for claim in response.claim_details)
        differences = (
            *self._claim_differences(extracted_types, self_reported_types),
            *self._structured_claim_differences(context, response.claim_details),
        )
        embodied_reasons = self._embodied_action_conflicts(context, response.speech)
        fact_reasons = self._fact_conflicts(
            context.status,
            extracted_types,
            ongoing_status=(
                context.ongoing_activity.ongoing_status
                if context.ongoing_activity is not None
                else None
            ),
        )
        transition_reasons = self._transition_conflicts(context, extracted_types)
        topic_reasons = self._autonomous_topic_conflicts(context, response.speech)
        directive_reasons = self._directive_conflicts(context, response.speech)
        reasons = tuple(
            dict.fromkeys(
                (
                    *embodied_reasons,
                    *fact_reasons,
                    *differences,
                    *topic_reasons,
                    *transition_reasons,
                    *directive_reasons,
                )
            )
        )
        accepted = not invalid_self_reported and not reasons
        reason = (
            "deterministic_facts_valid"
            if accepted
            else reasons[0] if reasons else "claims_conflict_with_result"
        )
        result = ResponseValidationResult(
            accepted=accepted,
            reason=reason,
            invalid_claims=invalid_self_reported,
            extracted_claims=extracted_claims,
            claim_differences=reasons,
        )
        fields = {
            "activity_type": context.activity_type,
            "operation": context.operation,
            "execution_status": context.status.value,
            "self_reported_claims": [claim.value for claim in response.claims],
            "self_reported_claim_details": [
                asdict(claim) for claim in response.claim_details
            ],
            "extracted_claims": [asdict(claim) for claim in extracted_claims],
            "claim_differences": list(reasons),
            "accepted": accepted,
        }
        if accepted:
            self._trace_logger.debug("response_fact_validator:accepted", **fields)
        else:
            self._trace_logger.info("response_fact_validator:rejected", **fields)
        self._causal_observer.observe_character_claim(context, result)
        return result

    @staticmethod
    def _invalid_self_reported(
        context: ResponseContext, response: CharacterResponse
    ) -> tuple[ResponseClaim, ...]:
        forbidden = tuple(
            claim for claim in response.claims if claim in context.forbidden_claims
        )
        unknown = tuple(
            claim for claim in response.claims if claim not in context.allowed_claims
        )
        return tuple(dict.fromkeys((*forbidden, *unknown)))

    @staticmethod
    def _embodied_action_conflicts(
        context: ResponseContext,
        speech: str,
    ) -> tuple[str, ...]:
        intention = context.interaction_intention
        if (
            intention is None
            or intention.intention is not InteractionIntentionType.ACT
            or _EMBODIED_ACTION_COMPLETION_PATTERN.search(speech) is None
        ):
            return ()
        if (
            context.activity_type != "conversation"
            and context.status is ActivityExecutionStatus.SUCCEEDED
        ):
            return ()
        return ("embodied_action_claim_without_execution_result",)

    @staticmethod
    def _fact_conflicts(
        status: ActivityExecutionStatus,
        extracted: set[ClaimType],
        *,
        ongoing_status: str | None,
    ) -> tuple[str, ...]:
        invalid: set[ClaimType]
        if status in {ActivityExecutionStatus.REJECTED, ActivityExecutionStatus.FAILED}:
            invalid = set(_POSITIVE_EXECUTION_CLAIMS)
        elif status == ActivityExecutionStatus.CANCELED:
            invalid = {
                ClaimType.ACTIVITY_RUNNING,
                ClaimType.ACTIVITY_CONTINUED,
                ClaimType.ACTIVITY_COMPLETED,
                ClaimType.ACTIVITY_SUCCEEDED,
                ClaimType.EXTERNAL_RESULT_OBTAINED,
            }
        elif status == ActivityExecutionStatus.WAITING_INPUT:
            invalid = set(_COMPLETION_CLAIMS)
        else:
            invalid = set()
        if ongoing_status == "waiting":
            invalid.update(_COMPLETION_CLAIMS)
        elif ongoing_status in {"completed", "canceled"}:
            invalid.update(
                {
                    ClaimType.ACTIVITY_RUNNING,
                    ClaimType.ACTIVITY_CONTINUED,
                }
            )
        conflicts = extracted & invalid
        ordered = sorted(conflicts, key=lambda item: item.value)
        return tuple(
            f"claim_not_supported_by_{status.value}:{claim.value}" for claim in ordered
        )

    @staticmethod
    def _claim_differences(
        extracted: set[ClaimType], self_reported: set[ClaimType]
    ) -> tuple[str, ...]:
        differences: list[str] = []
        extracted_positive = extracted & _POSITIVE_EXECUTION_CLAIMS
        reported_positive = self_reported & _POSITIVE_EXECUTION_CLAIMS
        extracted_negative = extracted & _NEGATIVE_EXECUTION_CLAIMS
        reported_negative = self_reported & _NEGATIVE_EXECUTION_CLAIMS
        if extracted_positive and not reported_positive:
            differences.append("speech_execution_claim_missing_from_self_report")
        if reported_positive and not extracted_positive:
            differences.append("self_reported_execution_claim_missing_from_speech")
        if extracted_positive and (
            ClaimType.CONVERSATION_ONLY in self_reported or reported_negative
        ):
            differences.append("speech_positive_self_report_negative")
        if extracted_negative and reported_positive:
            differences.append("speech_negative_self_report_positive")
        if (
            ClaimType.ACTIVITY_RUNNING in extracted
            and self_reported & _COMPLETION_CLAIMS
        ):
            differences.append("speech_running_self_report_completed")
        if (
            extracted & _COMPLETION_CLAIMS
            and ClaimType.ACTIVITY_CONTINUED in self_reported
        ):
            differences.append("speech_completed_self_report_continued")
        return tuple(differences)

    @staticmethod
    def _transition_conflicts(
        context: ResponseContext,
        extracted: set[ClaimType],
    ) -> tuple[str, ...]:
        conflicts: list[str] = []
        if context.current_activity_preserved and extracted & {
            ClaimType.ACTIVITY_COMPLETED,
            ClaimType.ACTIVITY_CANCELED,
        }:
            conflicts.append("preserved_activity_claimed_stopped")
        if (
            context.ongoing_input_decision
            in {"conversation_about_current", "conversation_unrelated"}
            and extracted & _POSITIVE_EXECUTION_CLAIMS
        ):
            conflicts.append("conversation_claimed_plugin_execution")
        if (
            context.requested_new_activity is not None
            and context.transition_result != "succeeded"
            and ClaimType.ACTIVITY_STARTED in extracted
        ):
            conflicts.append("failed_switch_claimed_new_activity_started")
        if (
            context.ongoing_input_decision == "stop_current"
            and not context.current_activity_stopped
            and ClaimType.ACTIVITY_COMPLETED in extracted
        ):
            conflicts.append("failed_stop_claimed_activity_completed")
        return tuple(conflicts)

    @staticmethod
    def _structured_claim_differences(
        context: ResponseContext,
        claims: tuple[Claim, ...],
    ) -> tuple[str, ...]:
        differences: list[str] = []
        for claim in claims:
            if (
                claim.activity_type is not None
                and claim.activity_type != context.activity_type
            ):
                differences.append("self_reported_activity_type_mismatch")
            if claim.operation is not None and claim.operation != context.operation:
                differences.append("self_reported_operation_mismatch")
            if claim.status is not None and claim.status != context.status:
                differences.append("self_reported_status_mismatch")
        return tuple(dict.fromkeys(differences))

    @classmethod
    def _directive_conflicts(
        cls,
        context: ResponseContext,
        speech: str,
    ) -> tuple[str, ...]:
        envelope_value = context.constraints.get("_internal_directive")
        if not isinstance(envelope_value, dict):
            return ()
        internal_value = envelope_value.get("internal_directive")
        meaning_value = envelope_value.get("structured_input_meaning")
        if not isinstance(internal_value, dict):
            return ()
        internal = dict(internal_value)
        meaning = dict(meaning_value) if isinstance(meaning_value, dict) else {}
        reasons: list[str] = []

        question_budget = 1 if internal.get("question_budget") == 1 else 0
        question_count = cls._question_count(speech)
        if question_count > question_budget:
            reasons.append("response_exceeds_internal_directive_question_budget")

        new_direction_budget = (
            1 if internal.get("new_direction_budget") == 1 else 0
        )
        new_direction_count = len(_EXPLICIT_NEW_DIRECTION_PATTERN.findall(speech))
        if new_direction_count > new_direction_budget:
            reasons.append(
                "response_exceeds_internal_directive_new_direction_budget"
            )

        speech_act = str(meaning.get("input_speech_act") or "").strip().lower()
        phase = str(meaning.get("conversation_phase_signal") or "").strip().lower()
        if speech_act == "closing" or phase == "winding_down":
            if question_count:
                reasons.append("closing_response_reopens_conversation")
            if len(speech.strip()) > 80:
                reasons.append("closing_response_too_long")

        boundaries_value = envelope_value.get("existence_boundaries")
        boundaries = (
            tuple(str(item) for item in boundaries_value)
            if isinstance(boundaries_value, (list, tuple))
            else ()
        )
        forbidden_value = internal.get("forbidden_claims")
        forbidden = (
            tuple(str(item) for item in forbidden_value)
            if isinstance(forbidden_value, (list, tuple))
            else ()
        )
        existence_text = "\n".join((*boundaries, *forbidden))
        if "実体験" in existence_text and _UNSUPPORTED_EXPERIENCE_PATTERN.search(speech):
            reasons.append("response_violates_existence_boundary")
        if (
            "物理的" in existence_text
            and "身体" in existence_text
            and _PHYSICAL_BODY_CLAIM_PATTERN.search(speech)
        ):
            reasons.append("response_violates_existence_boundary")

        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _question_count(speech: str) -> int:
        punctuation_count = speech.count("?") + speech.count("？")
        if punctuation_count:
            return punctuation_count
        clauses = (
            clause.strip()
            for clause in re.split(r"[。\n]+", speech)
            if clause.strip()
        )
        return sum(1 for clause in clauses if _QUESTION_ENDING_PATTERN.search(clause))

    @staticmethod
    def _autonomous_topic_conflicts(
        context: ResponseContext,
        speech: str,
    ) -> tuple[str, ...]:
        topic = (context.topic or "").strip()
        if (
            context.activity_type != "autonomous_talk"
            or len(topic) < 4
            or len(speech) < 8
        ):
            return ()
        if topic in {
            "いま気になっていること",
            "この配信でこれから話したいこと",
            "気分転換に考えてみたいこと",
            "いまの気分",
        }:
            return ()
        normalized_topic = re.sub(r"[\s、。！？!?・]", "", topic)
        normalized_speech = re.sub(r"[\s、。！？!?・]", "", speech)
        if len(normalized_topic) < 3:
            return ()
        topic_bigrams = {
            normalized_topic[index : index + 2]
            for index in range(len(normalized_topic) - 1)
        }
        if any(token in normalized_speech for token in topic_bigrams):
            return ()
        return ("autonomous_topic_drift",)
