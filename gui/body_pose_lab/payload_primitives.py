from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import fields
from typing import Any


class BodyPoseLabPayloadError(ValueError):
    """Labの公開JSON境界で検出した安全な入力エラー。"""


class BodyPoseLabPayloadReader:
    """JSON互換値の基本型・有限値・文字列を検証する。"""

    @staticmethod
    def mapping(value: object, name: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise BodyPoseLabPayloadError(f"{name} must be an object")
        return value

    @staticmethod
    def sequence(value: object, name: str) -> Sequence[object]:
        if isinstance(value, (str, bytes, bytearray)) or not isinstance(
            value, Sequence
        ):
            raise BodyPoseLabPayloadError(f"{name} must be an array")
        return value

    @staticmethod
    def number(value: object, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise BodyPoseLabPayloadError(f"{name} must be a number")
        normalized = float(value)
        if not math.isfinite(normalized):
            raise BodyPoseLabPayloadError(f"{name} must be finite")
        return normalized

    @staticmethod
    def integer(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise BodyPoseLabPayloadError(f"{name} must be an integer")
        return value

    @staticmethod
    def optional_string(value: object, name: str = "text") -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise BodyPoseLabPayloadError(f"{name} must be a string")
        normalized = value.strip()
        return normalized or None

    def dataclass_numbers(
        self,
        target: type[Any],
        payload: Mapping[str, object],
    ) -> dict[str, float]:
        return {
            field.name: self.number(payload[field.name], field.name)
            for field in fields(target)
            if field.name in payload
        }
