"""採用済みの入力と意味を、由来を変えず有界に保持する。"""

from collections import OrderedDict
from dataclasses import dataclass

from app.domain.input_gateway import (
    InputAdmission,
    InputAdmissionStatus,
    InputModality,
    NormalizedInputEvent,
)
from app.domain.input_meaning import InputMeaningInterpretationResult, StructuredInputMeaning


@dataclass(frozen=True, slots=True)
class CoreAcceptedInput:
    event: NormalizedInputEvent
    result: InputMeaningInterpretationResult

    def __post_init__(self) -> None:
        if not isinstance(self.event, NormalizedInputEvent) or not isinstance(
            self.result, InputMeaningInterpretationResult
        ):
            raise ValueError("入力根拠には型付きの元イベントと採用結果が必要です")
        event, result = self.event.envelope, self.result
        if (
            result.meaning is None
            or result.source_event_id != event.event_id
            or result.trace_id != event.trace_id
            or result.source_context_revision != event.revisions.source_context_revision
        ):
            raise ValueError("入力根拠の採用結果と元イベントが一致しません")

    @property
    def meaning(self) -> StructuredInputMeaning | None:
        return self.result.meaning


@dataclass(frozen=True, slots=True)
class CoreAcceptedInternalInput:
    """Gatewayが採用した内部イベント。意味解析の成功を捏造しない。"""

    event: NormalizedInputEvent

    @property
    def meaning(self) -> None:
        return None


class CoreAcceptedInputStore:
    def __init__(self, max_entries: int) -> None:
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("入力根拠の保持上限は正の整数が必要です")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, CoreAcceptedInput | CoreAcceptedInternalInput] = (
            OrderedDict()
        )

    def retain(self, event: NormalizedInputEvent, result: InputMeaningInterpretationResult) -> None:
        value = CoreAcceptedInput(event, result)
        self._retain(value)

    def retain_internal(self, admission: InputAdmission) -> None:
        if admission.status is not InputAdmissionStatus.ACCEPTED or admission.event is None:
            raise ValueError("内部契機はGatewayの採用結果が必要です")
        if admission.event.modality not in (
            InputModality.SUBSYSTEM,
            InputModality.LIFECYCLE,
            InputModality.TIMER,
        ):
            raise ValueError("内部契機として扱えない入力種別です")
        self._retain(CoreAcceptedInternalInput(admission.event))

    def _retain(self, value: CoreAcceptedInput | CoreAcceptedInternalInput) -> None:
        key = value.event.envelope.event_id
        previous = self._entries.get(key)
        if previous is not None:
            if previous != value:
                raise ValueError("保持中の同じイベントの入力根拠は変更できません")
            return
        self._entries[key] = value
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def read(
        self, event_id: str, source_context_revision: int
    ) -> CoreAcceptedInput | CoreAcceptedInternalInput:
        value = self._entries.get(event_id)
        if value is None:
            raise ValueError("採用済みの入力根拠が保持されていません")
        if value.event.envelope.revisions.source_context_revision != source_context_revision:
            raise ValueError("採用済みの入力根拠の文脈が一致しません")
        return value
