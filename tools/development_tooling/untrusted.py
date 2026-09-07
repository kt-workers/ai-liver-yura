"""untrustedなrepository/Issue/upload入力を実行せず、bounded dataとして読む境界。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from math import isfinite

MAX_UNTRUSTED_BYTES = 1_000_000
MAX_UNTRUSTED_DEPTH = 16
MAX_UNTRUSTED_CONTAINER_ITEMS = 256
MAX_UNTRUSTED_STRING_LENGTH = 16_384
MAX_UNTRUSTED_KEY_LENGTH = 256


def parse_bounded_json_object(
    payload: bytes, *, maximum_bytes: int = MAX_UNTRUSTED_BYTES
) -> Mapping[str, object]:
    """JSON objectだけをboundedに解析する。任意コード・設定・commandは実行しない。"""
    if type(maximum_bytes) is not int or maximum_bytes <= 0:
        raise ValueError("maximum_bytesは正の整数である必要があります")
    if not isinstance(payload, bytes) or len(payload) > maximum_bytes:
        raise ValueError("untrusted payloadが許容sizeを超えています")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("untrusted payloadは有効なUTF-8 JSONではありません") from error
    if not isinstance(value, dict):
        raise ValueError("untrusted payloadはJSON objectである必要があります")
    try:
        _validate_bounded_json(value)
    except RecursionError as error:
        raise ValueError("untrusted payloadが許容depthを超えています") from error
    return value


def _validate_bounded_json(value: object, *, depth: int = 0) -> None:
    if depth > MAX_UNTRUSTED_DEPTH:
        raise ValueError("untrusted payloadが許容depthを超えています")
    if value is None or type(value) in {bool, int, float, str}:
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("untrusted payloadに有限でない数値を含められません")
        if isinstance(value, str) and len(value) > MAX_UNTRUSTED_STRING_LENGTH:
            raise ValueError("untrusted payloadの文字列が長すぎます")
        return
    if isinstance(value, dict):
        if len(value) > MAX_UNTRUSTED_CONTAINER_ITEMS:
            raise ValueError("untrusted payloadのobject item数が多すぎます")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > MAX_UNTRUSTED_KEY_LENGTH:
                raise ValueError("untrusted payloadのkeyが不正です")
            _validate_bounded_json(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > MAX_UNTRUSTED_CONTAINER_ITEMS:
            raise ValueError("untrusted payloadのarray item数が多すぎます")
        for item in value:
            _validate_bounded_json(item, depth=depth + 1)
        return
    raise ValueError("untrusted payloadのJSON型が不正です")
