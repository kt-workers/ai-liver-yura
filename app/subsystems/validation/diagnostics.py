"""提供サービス側の安全な診断を、実行ごとの有限な記録として受け取る。"""

from app.adapters.llm.operational_diagnostics import LLMProviderOperationalDiagnostic
from app.domain.contracts.common import JsonValue, freeze_json

from .contracts import positive


class DiagnosticCollector:
    def __init__(self, maximum: int) -> None:
        positive(maximum)
        self._maximum = maximum
        self._items: list[LLMProviderOperationalDiagnostic] = []
        self.dropped_count = 0

    def publish(self, diagnostic: LLMProviderOperationalDiagnostic) -> None:
        if not isinstance(diagnostic, LLMProviderOperationalDiagnostic):
            raise ValueError("既存の安全な提供サービス診断だけを受理します")
        if len(self._items) >= self._maximum:
            self.dropped_count += 1
            return
        self._items.append(diagnostic)

    def snapshot(self) -> tuple[JsonValue, ...]:
        return tuple(freeze_json(item.to_dict()) for item in self._items)
