"""管理権限を持たない5経路の応答を、通信実装から分離する。"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .assets import CSS, HTML, JAVASCRIPT
from .configuration_projection import MinimumBrainConfigurationReadModelProjector

SAFE_HEADERS: tuple[tuple[str, str], ...] = (
    ("Cache-Control", "no-store"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    (
        "Content-Security-Policy",
        "default-src 'none'; script-src 'self'; style-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
)


@dataclass(frozen=True, slots=True)
class GuiHttpResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


def failure_response(status: int, code: str, *, head: bool = False) -> GuiHttpResponse:
    """内部で選択した固定の失敗コードのみを公開する。"""
    allowed = {
        "GUI_QUERY_NOT_ALLOWED": 400,
        "GUI_ROUTE_NOT_FOUND": 404,
        "GUI_METHOD_NOT_ALLOWED": 405,
        "GUI_REQUEST_BODY_NOT_ALLOWED": 413,
        "GUI_REQUEST_LIMIT_REACHED": 503,
        "GUI_REQUEST_TIMED_OUT": 503,
        "GUI_INTERNAL_TRANSPORT_FAILURE": 500,
    }
    if allowed.get(code) != status:
        raise ValueError("GUI応答の失敗コードが不正です")
    content = json.dumps({"error": {"code": code}}, separators=(",", ":")).encode()
    headers = SAFE_HEADERS + (
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(content))),
        ("Connection", "close"),
    )
    if status == 405:
        headers += (("Allow", "GET, HEAD"),)
    return GuiHttpResponse(status, headers, b"" if head else content)


class GuiHttpApplication:
    """注入済みの不変投影だけを公開し、ファイル探索やOwner操作をしない。"""

    def __init__(self, projector: MinimumBrainConfigurationReadModelProjector) -> None:
        self._routes = {
            b"/": ("text/html; charset=utf-8", HTML),
            b"/assets/app.js": ("text/javascript; charset=utf-8", JAVASCRIPT),
            b"/assets/app.css": ("text/css; charset=utf-8", CSS),
            b"/api/v1/configuration/minimum-brain": (
                "application/json; charset=utf-8",
                projector.json_bytes,
            ),
            b"/healthz": ("", b""),
        }

    def respond(self, method: bytes, target: bytes, *, has_body: bool) -> GuiHttpResponse:
        head = method == b"HEAD"
        if has_body:
            return failure_response(413, "GUI_REQUEST_BODY_NOT_ALLOWED", head=head)
        path, _, query = target.partition(b"?")
        if query:
            return failure_response(400, "GUI_QUERY_NOT_ALLOWED", head=head)
        route = self._routes.get(path)
        if route is None:
            return failure_response(404, "GUI_ROUTE_NOT_FOUND", head=head)
        if method not in (b"GET", b"HEAD"):
            return failure_response(405, "GUI_METHOD_NOT_ALLOWED")
        if path == b"/healthz":
            return GuiHttpResponse(204, SAFE_HEADERS + (("Connection", "close"),), b"")
        content_type, content = route
        return GuiHttpResponse(
            200,
            SAFE_HEADERS
            + (
                ("Content-Type", content_type),
                ("Content-Length", str(len(content))),
                ("Connection", "close"),
            ),
            b"" if head else content,
        )
