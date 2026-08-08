from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer
from typing import Any

_EXPECTED_CLIENT_DISCONNECTS = (
    BrokenPipeError,
    ConnectionAbortedError,
    ConnectionResetError,
)


def is_expected_client_disconnect(error: BaseException | None) -> bool:
    """ブラウザやSSEクライアントの通常切断かを判定する。"""

    return isinstance(error, _EXPECTED_CLIENT_DISCONNECTS)


class BodyPoseLabThreadingHttpServer(ThreadingHTTPServer):
    """予期されたクライアント切断だけを静かに処理するHTTP Server。"""

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        error = sys.exc_info()[1]
        if is_expected_client_disconnect(error):
            return
        super().handle_error(request, client_address)
