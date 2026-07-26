from __future__ import annotations

from app.runtime.agent_life_service import AgentLifeService


class TopicTrackingAgentLifeService(AgentLifeService):
    """互換Import用の別名クラス。

    話題管理は基底``AgentLifeService``自身が``AutonomousTopicTracker``へ委譲する。
    実行時の``__class__``変更は行わない。
    """
