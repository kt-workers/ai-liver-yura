from __future__ import annotations

from cloud_validation.v2_semantic_verification_lab import _PRESETS, app
from cloud_validation.v2_semantic_verification_matrix import EXTRA_PRESETS

_PRESETS.update(EXTRA_PRESETS)

__all__ = ["app"]
