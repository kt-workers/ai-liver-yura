"""旧Adapter import path向けの互換re-export。

認知指令用PromptBuilderはLLM Providerや外部I/Oへ依存しないため、
決定論的な共有層 ``app.prompting`` を正規配置とする。
"""

from app.prompting.cognitive_direction_prompt_builders import (
    InputMeaningPromptBuilder,
    InternalDirectivePromptBuilder,
)

__all__ = [
    "InputMeaningPromptBuilder",
    "InternalDirectivePromptBuilder",
]
