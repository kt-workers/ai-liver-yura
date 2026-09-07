"""証拠のJSON値を、実際の構造を確認してから試験で参照する。"""

from collections.abc import Mapping

from app.domain.contracts.common import JsonValue


def value_at(value: JsonValue, *path: str | int) -> JsonValue:
    for key in path:
        if isinstance(key, str):
            assert isinstance(value, Mapping)
            value = value[key]
        else:
            assert isinstance(value, tuple)
            value = value[key]
    return value


def object_at(value: JsonValue, *path: str | int) -> Mapping[str, JsonValue]:
    result = value_at(value, *path)
    assert isinstance(result, Mapping)
    return result


def array_at(value: JsonValue, *path: str | int) -> tuple[JsonValue, ...]:
    result = value_at(value, *path)
    assert isinstance(result, tuple)
    return result


def integer_at(value: JsonValue, *path: str | int) -> int:
    result = value_at(value, *path)
    assert isinstance(result, int) and not isinstance(result, bool)
    return result
