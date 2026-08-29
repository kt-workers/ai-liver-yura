"""Loop Engineeringの限定遷移を1回実行する制御済み統合構成。"""

from __future__ import annotations

from .runner import LoopRunner, RunnerResult


def run_controlled_transition(runner: LoopRunner) -> RunnerResult:
    """注入された実運用接続口を1回実行する。外部効果の責任は呼出側が持つ。"""
    return runner.run_once()
