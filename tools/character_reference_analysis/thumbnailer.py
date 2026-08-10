from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import imageio_ffmpeg


class FfmpegReferenceThumbnailer:
    """Create a small reference-only preview frame from a temporary video file."""

    def __init__(self, *, width: int = 480, seek_seconds: float = 0.5) -> None:
        if width <= 0:
            raise ValueError("thumbnail width must be > 0")
        if seek_seconds < 0:
            raise ValueError("thumbnail seek_seconds must be >= 0")
        self._width = width
        self._seek_seconds = seek_seconds

    async def extract_thumbnail(
        self,
        media_path: Path,
        output_directory: Path,
    ) -> Path:
        return await asyncio.to_thread(
            self._extract_thumbnail_sync,
            media_path,
            output_directory,
        )

    def _extract_thumbnail_sync(
        self,
        media_path: Path,
        output_directory: Path,
    ) -> Path:
        output_directory.mkdir(parents=True, exist_ok=True)
        output_path = output_directory / "reference-preview.jpg"
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

        command = self._build_command(
            ffmpeg,
            media_path,
            output_path,
            seek_seconds=self._seek_seconds,
        )
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            fallback = self._build_command(
                ffmpeg,
                media_path,
                output_path,
                seek_seconds=0.0,
            )
            result = subprocess.run(
                fallback,
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0 or not output_path.is_file():
            detail = (result.stderr or result.stdout or "ffmpeg failed").strip()
            raise RuntimeError(f"reference thumbnail generation failed: {detail[-1200:]}")
        return output_path

    def _build_command(
        self,
        ffmpeg: str,
        media_path: Path,
        output_path: Path,
        *,
        seek_seconds: float,
    ) -> list[str]:
        return [
            ffmpeg,
            "-y",
            "-ss",
            f"{seek_seconds:.3f}",
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={self._width}:-2",
            "-q:v",
            "4",
            str(output_path),
        ]
