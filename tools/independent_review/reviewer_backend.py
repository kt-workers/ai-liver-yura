from __future__ import annotations

from typing import Protocol

from .models import ProviderReviewCandidate, ReviewContext


class ReviewerBackendError(RuntimeError):
    pass


class ReviewerBackend(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def review(self, context: ReviewContext) -> ProviderReviewCandidate: ...
