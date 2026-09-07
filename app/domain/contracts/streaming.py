"""配信実装を読み込まずに参照できる、集約済み配信信号の公開契約。"""

from dataclasses import dataclass
from datetime import datetime

from .common import require_aware, require_identifier


@dataclass(frozen=True, slots=True)
class StreamingCommentSignal:
    signal_id: str
    source_channel_ref: str
    representative_event_id: str
    count: int
    generated_at: datetime

    def __post_init__(self) -> None:
        for name in ("signal_id", "source_channel_ref", "representative_event_id"):
            require_identifier(getattr(self, name), name)
        if type(self.count) is not int or self.count < 1:
            raise ValueError("comment signal count が不正です")
        require_aware(self.generated_at, "generated_at")
