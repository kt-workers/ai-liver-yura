"""Character reference analysis helpers.

This package is intentionally outside the Yura runtime.  Reference media is used
only to broaden design exploration and must never become reusable character assets.
"""

from .models import (
    ReferenceSource,
    ReferenceSourceKind,
    ReferenceUsagePolicy,
    Transcript,
    TranscriptSegment,
    TranscriptionMetadata,
)
from .ports import TranscriptionBackend

__all__ = [
    "ReferenceSource",
    "ReferenceSourceKind",
    "ReferenceUsagePolicy",
    "Transcript",
    "TranscriptSegment",
    "TranscriptionBackend",
    "TranscriptionMetadata",
]
