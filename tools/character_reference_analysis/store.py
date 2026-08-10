from __future__ import annotations

from typing import Protocol

from .manifest import ReferenceAnalysisManifest
from .models import Transcript


class ReferenceResultStore(Protocol):
    """Cloud-persistent result boundary.

    Production adapters must persist outside the Render/local ephemeral filesystem.
    """

    async def has_revision(self, revision_key: str) -> bool:
        """Return whether this exact source revision already has a manifest."""

    async def load_manifest(
        self, revision_key: str
    ) -> ReferenceAnalysisManifest | None:
        """Load one source-revision manifest when present."""

    async def save_manifest(self, manifest: ReferenceAnalysisManifest) -> None:
        """Persist or replace one analysis manifest."""

    async def save_transcript(self, transcript: Transcript, *, revision_key: str) -> None:
        """Persist normalized transcript JSON/readable text for one revision."""
