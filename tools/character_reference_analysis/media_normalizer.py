from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class MediaNormalizationError(RuntimeError):
    pass


class ReferenceMediaNormalizer(Protocol):
    async def extract_audio(self, media_path: Path, output_directory: Path) -> Path:
        """Create a temporary ASR-compatible audio file; never a reusable asset."""


class FfmpegAudioNormalizer:
    """Extract mono MP3 for ASR while keeping source media reference-only."""

    def __init__(
        self,
        *,
        ffmpeg_bin_env: str = "YURA_REFERENCE_FFMPEG_BIN",
        sample_rate: int = 16000,
        bitrate: str = "64k",
    ) -> None:
        self._ffmpeg_bin_env = ffmpeg_bin_env
        self._sample_rate = sample_rate
        self._bitrate = bitrate

    async def extract_audio(self, media_path: Path, output_directory: Path) -> Path:
        return await asyncio.to_thread(
            self._extract_audio_sync,
            media_path,
            output_directory,
        )

    def _extract_audio_sync(self, media_path: Path, output_directory: Path) -> Path:
        if not media_path.is_file():
            raise MediaNormalizationError(f"media file not found: {media_path}")
        ffmpeg = self._resolve_ffmpeg()
        output_directory.mkdir(parents=True, exist_ok=True)
        output = output_directory / "reference-audio.mp3"
        command = self._build_command(ffmpeg, media_path, output)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise MediaNormalizationError(
                "ffmpeg audio extraction failed: " + completed.stderr[-2000:]
            )
        if not output.is_file() or output.stat().st_size == 0:
            raise MediaNormalizationError("ffmpeg produced no audio output")
        return output

    def _resolve_ffmpeg(self) -> str:
        configured = os.environ.get(self._ffmpeg_bin_env)
        if configured:
            return configured
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            return system_ffmpeg
        try:
            import imageio_ffmpeg  # type: ignore[import-not-found]
        except ImportError as error:
            raise MediaNormalizationError(
                "ffmpeg is unavailable; install ffmpeg or imageio-ffmpeg"
            ) from error
        return imageio_ffmpeg.get_ffmpeg_exe()

    def _build_command(self, ffmpeg: str, media_path: Path, output: Path) -> list[str]:
        return [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(media_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            str(self._sample_rate),
            "-b:a",
            self._bitrate,
            str(output),
        ]
