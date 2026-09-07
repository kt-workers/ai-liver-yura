"""採用済みの入力と意味を、由来を変えず有界に保持する。"""

from collections import OrderedDict
from dataclasses import dataclass

from app.domain.input_gateway import NormalizedInputEvent
from app.domain.input_meaning import InputMeaningInterpretationResult


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


class CoreAcceptedInputStore:
    def __init__(self, max_entries: int) -> None:
        if type(max_entries) is not int or max_entries <= 0:
            raise ValueError("入力根拠の保持上限は正の整数が必要です")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, CoreAcceptedInput] = OrderedDict()

    def retain(self, event: NormalizedInputEvent, result: InputMeaningInterpretationResult) -> None:
        value = CoreAcceptedInput(event, result)
        key = event.envelope.event_id
        previous = self._entries.get(key)
        if previous is not None:
            if previous != value:
                raise ValueError("保持中の同じイベントの入力根拠は変更できません")
            return
        self._entries[key] = value
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def read(self, event_id: str, source_context_revision: int) -> CoreAcceptedInput:
        value = self._entries.get(event_id)
        if value is None:
            raise ValueError("採用済みの入力根拠が保持されていません")
        if value.result.source_context_revision != source_context_revision:
            raise ValueError("採用済みの入力根拠の文脈が一致しません")
        return value
