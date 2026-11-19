"""Synthetic media builders shared by the detection tests.

Everything here needs ffmpeg; tests that use it take the ``ffmpeg_available``
fixture so they skip cleanly instead of failing on a machine without it.
"""

from __future__ import annotations

import subprocess
import wave
from collections.abc import Sequence
from pathlib import Path

RATE = 16000


def run_ffmpeg(args: Sequence[str], *, timeout: float = 300.0) -> None:
    """Run ffmpeg with an argument list; raise on failure with its output."""
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"ffmpeg failed: {completed.stderr.strip()}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return float(handle.getnframes()) / float(handle.getframerate())


def tone_bursts(
    path: Path,
    *,
    speech: float = 1.0,
    silence: float = 1.0,
    repeats: int = 3,
    noise: bool = False,
) -> Path:
    """Alternating 440 Hz bursts and digital silence, with known boundaries."""
    args: list[str] = []
    for _ in range(repeats):
        args += [
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={speech}:sample_rate={RATE}",
        ]
        args += ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=mono:d={silence}"]

    count = repeats * 2
    labels = "".join(f"[{index}:a]" for index in range(count))
    if noise:
        total = repeats * (speech + silence)
        args += [
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=white:amplitude=0.02:sample_rate={RATE}:duration={total}",
        ]
        chain = f"{labels}concat=n={count}:v=0:a=1[base]"
        chain += f";[base][{count}:a]amix=inputs=2:duration=first:normalize=0"
    else:
        chain = f"{labels}concat=n={count}:v=0:a=1"

    run_ffmpeg(
        [*args, "-filter_complex", chain, "-ac", "1", "-ar", str(RATE), str(path)]
    )
    return path


def all_silence(path: Path, *, seconds: float = 3.0) -> Path:
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={RATE}:cl=mono:d={seconds}",
            "-ac",
            "1",
            "-ar",
            str(RATE),
            str(path),
        ]
    )
    return path


def speech_pattern(
    path: Path,
    speech_wav: Path,
    *,
    silence: float = 1.0,
    repeats: int = 2,
) -> list[tuple[float, float]]:
    """Real speech blocks separated by known silence; returns the truth windows."""
    block = wav_duration(speech_wav)
    args: list[str] = []
    for _ in range(repeats):
        args += ["-i", str(speech_wav)]
        args += ["-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=mono:d={silence}"]

    count = repeats * 2
    chain = "".join(f"[{index}:a]" for index in range(count))
    chain += f"concat=n={count}:v=0:a=1"
    run_ffmpeg(
        [*args, "-filter_complex", chain, "-ac", "1", "-ar", str(RATE), str(path)]
    )
    return [
        (index * (block + silence), index * (block + silence) + block)
        for index in range(repeats)
    ]


def video_clip(
    path: Path,
    *,
    audio: Path | None = None,
    seconds: float = 2.0,
    fps: int = 30,
    size: str = "320x240",
) -> Path:
    """A tiny H.264 clip, optionally muxed with a WAV's audio."""
    args = ["-f", "lavfi", "-i", f"testsrc=size={size}:rate={fps}:duration={seconds}"]
    if audio is not None:
        args += [
            "-i",
            str(audio),
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:a",
            "aac",
            "-shortest",
        ]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    run_ffmpeg(args)
    return path


def vfr_video(path: Path, *, seconds: float = 3.0) -> Path:
    """Variable-frame-rate clip (phone-style irregular timestamps)."""
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc=size=320x240:rate=30:duration={seconds}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}:sample_rate={RATE}",
            "-vf",
            "select=not(eq(mod(n\\,7)\\,3))",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ]
    )
    return path
