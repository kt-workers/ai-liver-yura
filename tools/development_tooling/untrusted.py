"""untrustedなrepository/Issue/upload入力を実行せず、bounded dataとして読む境界。"""

from __future__ import annotations

import json
from collections.abc import Mapping

MAX_UNTRUSTED_BYTES = 1_000_000


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
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("untrusted payloadは有効なUTF-8 JSONではありません") from error
    if not isinstance(value, dict):
        raise ValueError("untrusted payloadはJSON objectである必要があります")
    return value
