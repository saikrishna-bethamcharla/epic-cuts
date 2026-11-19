"""Shared test helpers."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import pytest


def make_clips(directory: Path, names: list[str]) -> list[Path]:
    """Create empty files with the given names (no media, fast)."""
    directory.mkdir(parents=True, exist_ok=True)
    paths = [directory / name for name in names]
    for path in paths:
        path.write_bytes(b"")
    return paths


def no_probe(_path: Path) -> tuple[None, None]:
    """A prober that never touches the filesystem."""
    return None, None


class ClipBuilder(Protocol):
    """Builds a synthetic clip inside the test's temporary folder."""

    def __call__(
        self, name: str, *, seconds: float = 2.0, with_audio: bool = True
    ) -> Path: ...


@pytest.fixture(scope="session")
def speech_wav() -> Path:
    """1.568 s of continuous speech (public-domain JFK sample, see LICENSES)."""
    path = Path(__file__).parent / "fixtures" / "speech" / "jfk_speech_1_5s.wav"
    if not path.exists():  # pragma: no cover - fixture ships with the repo
        pytest.skip(f"speech fixture missing: {path}")
    return path


@pytest.fixture(scope="session")
def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


@pytest.fixture
def tone_clip(tmp_path: Path, ffmpeg_available: bool) -> Iterator[ClipBuilder]:
    """Synthetic media generated with ffmpeg; skips when ffmpeg is missing."""
    if not ffmpeg_available:
        pytest.skip("ffmpeg/ffprobe not installed")

    def build(name: str, *, seconds: float = 2.0, with_audio: bool = True) -> Path:
        target = tmp_path / name
        command = [
            "ffmpeg",
            "-hide_banner",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=30:duration={seconds}",
        ]
        if with_audio:
            command += [
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=1000:duration={seconds}",
                "-c:a",
                "aac",
                "-shortest",
            ]
        command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(target)]
        subprocess.run(command, check=True, capture_output=True, timeout=180)
        return target

    yield build
