from __future__ import annotations

import math


def finite_number(value: object, name: str) -> float:
    """boolを除く有限数へ正規化する。"""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def bounded_number(
    value: object,
    name: str,
    minimum: float,
    maximum: float,
) -> float:
    """有限数を指定範囲へ検証する。Clampは行わない。"""

    normalized = finite_number(value, name)
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return normalized


def non_negative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must not be negative")
    return value


def normalized_identifier(
    value: object,
    name: str,
    *,
    maximum_length: int = 80,
    lowercase: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if lowercase:
        normalized = normalized.lower()
    if not normalized or len(normalized) > maximum_length:
        raise ValueError(
            f"{name} must contain 1 to {maximum_length} characters"
        )
    return normalized
