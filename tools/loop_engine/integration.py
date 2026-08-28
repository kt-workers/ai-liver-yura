"""Controlled integration composition for one Loop Engineering transition."""

from __future__ import annotations

from .runner import LoopRunner, RunnerResult


def run_controlled_transition(runner: LoopRunner) -> RunnerResult:
    """Run the injected production ports once; callers own all external effects."""
    return runner.run_once()
