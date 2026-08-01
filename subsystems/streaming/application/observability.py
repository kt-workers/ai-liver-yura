"""Secret-safe application diagnostics independent from Core tracing."""

import logging


class StreamingApplicationLogger:
    def __init__(self) -> None:
        self._logger = logging.getLogger("subsystems.streaming")

    def debug(self, event: str, **fields: object) -> None:
        self._write(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: object) -> None:
        self._write(logging.INFO, event, fields)

    def warning(self, event: str, **fields: object) -> None:
        self._write(logging.WARNING, event, fields)

    def _write(self, level: int, event: str, fields: dict[str, object]) -> None:
        self._logger.log(level, "%s fields=%s", event, ",".join(sorted(fields)))
