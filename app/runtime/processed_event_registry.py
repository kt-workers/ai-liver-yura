from __future__ import annotations

from collections import deque


class ProcessedEventRegistry:
    """処理済みEvent IDを上限付きで保持する重複排除レジストリ。"""

    def __init__(self, *, capacity: int = 1024) -> None:
        if capacity <= 0:
            raise ValueError("capacity は1以上である必要があります。")
        self._event_ids: deque[str] = deque(maxlen=capacity)
        self._event_id_set: set[str] = set()

    @property
    def capacity(self) -> int:
        return self._event_ids.maxlen or 0

    def contains(self, event_id: str) -> bool:
        return event_id in self._event_id_set

    def register(self, event_id: str) -> bool:
        """未登録なら追加してTrue、登録済みならFalseを返す。"""

        if event_id in self._event_id_set:
            return False
        if len(self._event_ids) == self._event_ids.maxlen:
            oldest = self._event_ids[0]
            self._event_id_set.discard(oldest)
        self._event_ids.append(event_id)
        self._event_id_set.add(event_id)
        return True
