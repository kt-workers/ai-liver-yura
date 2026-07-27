from __future__ import annotations


class ConfigError(RuntimeError):
    """A configuration error that identifies its source and YAML path."""

    def __init__(
        self,
        *,
        path: str,
        expected: str,
        actual: str | None = None,
        cause: str | None = None,
        source_file: str | None = None,
    ) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        self.cause = cause
        self.source_file = source_file
        super().__init__(self._message())

    def with_source(self, source_file: str) -> ConfigError:
        return ConfigError(
            path=self.path,
            expected=self.expected,
            actual=self.actual,
            cause=self.cause,
            source_file=source_file,
        )

    def _message(self) -> str:
        parts = [f"設定エラー: path={self.path}", f"expected={self.expected}"]
        if self.actual is not None:
            parts.append(f"actual={self.actual}")
        if self.cause is not None:
            parts.append(f"cause={self.cause}")
        if self.source_file is not None:
            parts.append(f"source={self.source_file}")
        return ", ".join(parts)
