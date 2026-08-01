from __future__ import annotations

from app.runtime.agent_state import AgentState
from app.runtime.motivation_appraiser import MotivationAppraiser


class AutonomousMotivationContextBuilder:
    """自律計画で参照するMotivation Appraisalを読み取り専用で構築する。"""

    def __init__(self, appraiser: MotivationAppraiser | None = None) -> None:
        self._appraiser = appraiser or MotivationAppraiser()

    def build(self, state: AgentState) -> dict[str, object]:
        relationship = state.relationship_memory.current
        appraisal = self._appraiser.appraise(
            state.current_desire,
            relationship,
            moral_profile=state.moral_profile,
            moral_state=state.current_moral,
        )
        return appraisal.as_context()
