import pytest

from subsystems.streaming.adapters.repositories.in_memory_run_of_show_repository import (
    InMemoryRunOfShowRepository,
)
from subsystems.streaming.domain import RunOfShowSegment, RunOfShowSummary


def test_run_of_show_repository_orders_and_selects_segments() -> None:
    summary = RunOfShowSummary("show", "Show", 30, 3, "memory", "1")
    values = (
        RunOfShowSegment("close", "closing", "Close", 10, True, "p", "c", 2),
        RunOfShowSegment("open", "opening", "Open", 10, True, "p", "o", 0),
        RunOfShowSegment("main", "main", "Main", 10, True, "p", "m", 1),
    )
    repository = InMemoryRunOfShowRepository(((summary, values),))
    assert repository.get_opening_segment("show").segment_id == "open"
    assert repository.get_first_main_segment("show").segment_id == "main"
    assert repository.get_closing_segment("show").segment_id == "close"


def test_run_of_show_repository_rejects_unknown_show() -> None:
    with pytest.raises(ValueError, match="run_of_show.not_found"):
        InMemoryRunOfShowRepository().load("missing")
