from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest

_SCHEMA_VERSION = "1.0.0"
_DEFAULT_PREFIX = "extended_"
_DEFAULT_TIMEOUT_SECONDS = 180.0


class BatchRequestError(RuntimeError):
    """Lab API呼び出し自体に失敗したことを表す。"""


def _authorization_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request_json(
    *,
    base_url: str,
    path: str,
    username: str,
    password: str,
    timeout_seconds: float,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    body = None
    method = "GET"
    headers = {
        "Accept": "application/json",
        "Authorization": _authorization_header(username, password),
    }
    if payload is not None:
        method = "POST"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"

    http_request = urlrequest.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urlrequest.urlopen(http_request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BatchRequestError(
            f"HTTP {exc.code} {method} {path}: {detail[:1000]}"
        ) from exc
    except urlerror.URLError as exc:
        raise BatchRequestError(f"接続失敗 {method} {path}: {exc.reason}") from exc

    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BatchRequestError(f"JSONではない応答 {method} {path}") from exc
    if not isinstance(value, dict):
        raise BatchRequestError(f"object JSONではない応答 {method} {path}")
    return dict(value)


def _select_presets(
    presets: dict[str, object],
    *,
    prefix: str,
    explicit_keys: tuple[str, ...] = (),
) -> list[tuple[str, str, dict[str, object]]]:
    selected: list[tuple[str, str, dict[str, object]]] = []
    wanted = set(explicit_keys)
    for key, value in presets.items():
        if explicit_keys:
            if key not in wanted:
                continue
        elif not key.startswith(prefix):
            continue
        if not isinstance(value, dict):
            continue
        data = value.get("data")
        if not isinstance(data, dict):
            continue
        label_value = value.get("label")
        label = label_value if isinstance(label_value, str) else key
        selected.append((key, label, deepcopy(data)))

    if explicit_keys:
        found = {key for key, _, _ in selected}
        missing = [key for key in explicit_keys if key not in found]
        if missing:
            raise ValueError(f"存在しないpreset: {', '.join(missing)}")
        selected.sort(key=lambda item: explicit_keys.index(item[0]))
    return selected


def _result_summary(result: dict[str, object]) -> str:
    generation = result.get("generation_result")
    if not isinstance(generation, dict):
        return "generation_resultなし"
    status = generation.get("status")
    attempts = generation.get("attempts")
    return f"status={status!s}, attempts={attempts!s}"


RequestJson = Callable[..., dict[str, object]]
Progress = Callable[[str], None]


def run_batch(
    *,
    base_url: str,
    username: str,
    password: str,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    prefix: str = _DEFAULT_PREFIX,
    explicit_keys: tuple[str, ...] = (),
    include_prompts: bool = False,
    request_json: RequestJson | None = None,
    progress: Progress | None = None,
) -> dict[str, object]:
    requester = request_json or _request_json
    report = progress or print

    health = requester(
        base_url=base_url,
        path="/health",
        username=username,
        password=password,
        timeout_seconds=timeout_seconds,
        payload=None,
    )
    presets = requester(
        base_url=base_url,
        path="/api/presets",
        username=username,
        password=password,
        timeout_seconds=timeout_seconds,
        payload=None,
    )
    selected = _select_presets(
        presets,
        prefix=prefix,
        explicit_keys=explicit_keys,
    )
    if not selected:
        raise ValueError(f"対象presetがありません: prefix={prefix!r}")

    cases: list[dict[str, object]] = []
    transport_error_count = 0
    total = len(selected)
    for index, (key, label, data) in enumerate(selected, start=1):
        request_payload = deepcopy(data)
        request_payload["include_prompts"] = include_prompts
        report(f"[{index}/{total}] {label} ({key}) 実行中...")
        entry: dict[str, object] = {
            "preset_key": key,
            "label": label,
            "request": deepcopy(request_payload),
        }
        try:
            result = requester(
                base_url=base_url,
                path="/api/character-response",
                username=username,
                password=password,
                timeout_seconds=timeout_seconds,
                payload=request_payload,
            )
        except Exception as exc:  # 各ケースの失敗を記録して残りを継続する
            transport_error_count += 1
            entry["runner_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
            report(f"[{index}/{total}] {label} API ERROR: {exc}")
        else:
            entry["result"] = result
            report(f"[{index}/{total}] {label} 完了 ({_result_summary(result)})")
        cases.append(entry)

    return {
        "schema_version": _SCHEMA_VERSION,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url.rstrip("/"),
        "health": health,
        "preset_prefix": prefix,
        "selected_preset_keys": [key for key, _, _ in selected],
        "transport_error_count": transport_error_count,
        "semantic_pass_fail_automatically_decided": False,
        "cases": cases,
    }


def _default_output_path() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(f"character-semantic-extended-{stamp}.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Yura Character Semantic LabのExtended Verification presetを逐次実行し、"
            "1つのJSONへ収集します。Semantic PASS/FAILは自動判定しません。"
        )
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("YURA_CHARACTER_SEMANTIC_LAB_URL", ""),
        help="Render上のSemantic Lab URL。YURA_CHARACTER_SEMANTIC_LAB_URLでも指定可能。",
    )
    parser.add_argument(
        "--username",
        default=os.getenv("YURA_LAB_USERNAME", ""),
        help="Basic Auth username。既定はYURA_LAB_USERNAME。",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("YURA_LAB_PASSWORD", ""),
        help=(
            "Basic Auth password。既定はYURA_LAB_PASSWORD。"
            "shell historyを避けるため環境変数利用を推奨。"
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT_SECONDS,
        help="1 API requestあたりのtimeout秒。既定180秒。",
    )
    parser.add_argument(
        "--prefix",
        default=_DEFAULT_PREFIX,
        help="一括選択するpreset key prefix。既定extended_。",
    )
    parser.add_argument(
        "--preset",
        action="append",
        default=[],
        help="特定presetだけ実行する場合に指定。複数回指定可能。",
    )
    parser.add_argument(
        "--include-prompts",
        action="store_true",
        help="結果JSONへmodel promptを含める。通常は不要。",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力JSON path。未指定時はtimestamp付きファイル名。",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.base_url.strip():
        print("--base-url または YURA_CHARACTER_SEMANTIC_LAB_URL が必要です", file=sys.stderr)
        return 2
    if not args.username or not args.password:
        print(
            "YURA_LAB_USERNAME / YURA_LAB_PASSWORD（または対応CLI引数）が必要です",
            file=sys.stderr,
        )
        return 2
    if args.timeout <= 0:
        print("--timeout は0より大きい値が必要です", file=sys.stderr)
        return 2

    output = args.output or _default_output_path()
    try:
        result = run_batch(
            base_url=args.base_url.strip(),
            username=args.username,
            password=args.password,
            timeout_seconds=args.timeout,
            prefix=args.prefix,
            explicit_keys=tuple(args.preset),
            include_prompts=args.include_prompts,
        )
    except (BatchRequestError, ValueError) as exc:
        print(f"一括実行を開始できませんでした: {exc}", file=sys.stderr)
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"結果を書き出しました: {output}")
    print("注意: このコマンドはSemantic PASS/FAILを自動判定していません。")
    return 1 if result["transport_error_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
