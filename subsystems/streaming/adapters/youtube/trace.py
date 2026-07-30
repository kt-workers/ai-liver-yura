"""Small structured trace boundary without Core logging dependencies."""

from __future__ import annotations

import logging
from typing import Protocol


class YouTubeTrace(Protocol):
    def info(self, event: str, **fields: object) -> None: ...

    def warning(self, event: str, **fields: object) -> None: ...


class StandardYouTubeTrace:
    def __init__(self) -> None:
        self._logger = logging.getLogger("streaming_subsystem.youtube")

    def info(self, event: str, **fields: object) -> None:
        self._logger.info("%s %s", event, fields)

    def warning(self, event: str, **fields: object) -> None:
        self._logger.warning("%s %s", event, fields)
