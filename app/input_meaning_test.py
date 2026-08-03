from __future__ import annotations

from typing import Any

import app.__main__ as app_main
from app.diagnostics import install_input_meaning_test


def main() -> None:
    """通常起動し、USER_TEXTだけを意味解析LLMの直後で停止する。"""

    original_factory = app_main.create_runtime_coordinator

    def diagnostic_runtime_factory(
        config: Any,
        *,
        web_conversation_enabled: bool | None = None,
    ) -> Any:
        runtime = original_factory(
            config,
            web_conversation_enabled=web_conversation_enabled,
        )
        install_input_meaning_test(runtime)
        return runtime

    print(
        "意味解析LLMテストモードで起動します。"
        "ユーザー入力はStructuredInputMeaningの出力後に停止します。"
    )
    print(
        "Internal Directive、Activity、Character応答、TTSは"
        "ユーザー入力Turnでは実行されません。"
    )
    setattr(
        app_main,
        "create_runtime_coordinator",
        diagnostic_runtime_factory,
    )
    try:
        app_main.main()
    finally:
        setattr(
            app_main,
            "create_runtime_coordinator",
            original_factory,
        )


if __name__ == "__main__":
    main()
