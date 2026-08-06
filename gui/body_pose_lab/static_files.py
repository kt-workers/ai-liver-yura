from __future__ import annotations

from dataclasses import dataclass
from mimetypes import guess_type
from pathlib import Path
from urllib.parse import unquote


@dataclass(frozen=True, slots=True)
class BodyPoseLabStaticFile:
    content: bytes
    content_type: str


class BodyPoseLabStaticFiles:
    """許可されたWeb Root内だけから静的資産を解決する。"""

    def __init__(self, web_root: Path) -> None:
        root = web_root.resolve()
        if not root.is_dir():
            raise ValueError("web_root must be an existing directory")
        self._web_root = root

    def resolve(self, request_path: str) -> BodyPoseLabStaticFile | None:
        path = unquote(request_path.split("?", 1)[0])
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        candidate = (self._web_root / relative).resolve()
        try:
            candidate.relative_to(self._web_root)
        except ValueError:
            return None
        if not candidate.is_file():
            return None
        content_type = guess_type(candidate.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
        }:
            content_type = f"{content_type}; charset=utf-8"
        return BodyPoseLabStaticFile(candidate.read_bytes(), content_type)
