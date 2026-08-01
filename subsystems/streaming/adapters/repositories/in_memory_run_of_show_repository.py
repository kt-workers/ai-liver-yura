"""Immutable in-memory Run of Show repository."""

from subsystems.streaming.domain import RunOfShowSegment, RunOfShowSummary


class InMemoryRunOfShowRepository:
    def __init__(
        self,
        shows: tuple[tuple[RunOfShowSummary, tuple[RunOfShowSegment, ...]], ...] = (),
    ) -> None:
        self._shows = {summary.run_of_show_id: summary for summary, _ in shows}
        self._segments = {
            summary.run_of_show_id: tuple(sorted(segments, key=lambda item: item.order))
            for summary, segments in shows
        }

    def list_available(self) -> tuple[RunOfShowSummary, ...]:
        return tuple(self._shows[key] for key in sorted(self._shows))

    def load(self, run_of_show_id: str) -> RunOfShowSummary:
        try:
            return self._shows[run_of_show_id]
        except KeyError as error:
            raise ValueError("run_of_show.not_found") from error

    def validate(self, run_of_show_id: str) -> RunOfShowSummary:
        return self.load(run_of_show_id)

    def get_opening_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        return self._first(run_of_show_id, "opening")

    def get_first_main_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        return self._first(run_of_show_id, "main")

    def get_closing_segment(self, run_of_show_id: str) -> RunOfShowSegment | None:
        return self._first(run_of_show_id, "closing")

    def _first(self, run_of_show_id: str, kind: str) -> RunOfShowSegment | None:
        self.load(run_of_show_id)
        return next(
            (
                segment
                for segment in self._segments.get(run_of_show_id, ())
                if segment.segment_type == kind
            ),
            None,
        )
