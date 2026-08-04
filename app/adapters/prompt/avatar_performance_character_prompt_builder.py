from __future__ import annotations

from app.adapters.prompt.directive_aware_prompt_builders import (
    CharacterPromptBuilder as DirectiveAwareCharacterPromptBuilder,
)
from app.domain.character import CharacterProfile
from app.domain.character_response import ResponseContext


class AvatarPerformanceCharacterPromptBuilder(DirectiveAwareCharacterPromptBuilder):
    """Character表現へエンジン非依存のAvatar演技Intentだけを追加する。"""

    def build(
        self,
        context: ResponseContext,
        *,
        character_profile: CharacterProfile | None,
        correction: str | None,
    ) -> str:
        prompt = super().build(
            context,
            character_profile=character_profile,
            correction=correction,
        )
        return "\n".join(
            [
                prompt,
                "# Avatar Performance Intent",
                "reaction_segmentsの各要素では、必要な場合だけ次の高レベル項目を追加する。",
                "expression_intensityとgesture_intensityは0.0〜1.0。未指定時は1.0。",
                "gazeはnullまたは{target, behavior, intensity}。targetはviewer、speaker、"
                "object、down、away、wander、neutralなどの意味名を使い、intensityは0.0〜1.0。",
                "視線、表情、Gestureは発話内容と内部感情に根拠がある場合だけ指定し、"
                "数値や項目を埋めるために不必要な演技を追加しない。",
                "performance_id、priority、duration_ms、fade、interrupt_policy、"
                "Live2D Parameter、VTube Studio Hotkeyは出力しない。これらはCoreと"
                "Avatar Runtimeが決定する。",
            ]
        )
