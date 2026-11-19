"""Energy detector: FFmpeg ``silencedetect`` on the selected audio track.

Fast, dependency-free and predictable — it needs only ffmpeg, so this is the
detector that always works. Silences are found by the filter and inverted into
keep segments here.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from autocut.analysis.base import (
    DetectorSettings,
    NoAudioStreamError,
    Segment,
)
from autocut.errors import ProcessingError, ToolMissingError
from autocut.media.tools import FFMPEG, find_tool, install_hint

DETECTOR_VERSION = "1"

_SILENCE_START = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class _Silence:
    start: float
    end: float


def parse_silencedetect(stderr: str, *, duration: float) -> list[_Silence]:
    """Turn ``silencedetect`` log lines into silence intervals.

    ``silence_start`` without a matching ``silence_end`` means the clip ends in
    silence, which is closed at ``duration``.
    """
    silences: list[_Silence] = []
    pending: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START.search(line)
        if start_match is not None:
            pending = max(0.0, float(start_match.group(1)))
            continue
        end_match = _SILENCE_END.search(line)
        if end_match is not None and pending is not None:
            end = min(duration, float(end_match.group(1)))
            if end > pending:
                silences.append(_Silence(start=pending, end=end))
            pending = None
    if pending is not None and duration > pending:
        silences.append(_Silence(start=pending, end=duration))
    return silences


def invert_silences(silences: list[_Silence], *, duration: float) -> list[Segment]:
    """Silence intervals -> keep segments covering everything else."""
    segments: list[Segment] = []
    cursor = 0.0
    for silence in sorted(silences, key=lambda item: item.start):
        if silence.start > cursor:
            segments.append(Segment(start=cursor, end=min(silence.start, duration)))
        cursor = max(cursor, silence.end)
    if cursor < duration:
        segments.append(Segment(start=cursor, end=duration))
    return [segment for segment in segments if segment.duration > 0]


class EnergyDetector:
    """``silencedetect``-based detector (default threshold -35 dB, 0.5 s)."""

    name = "energy"
    version = DETECTOR_VERSION

    def detect(
        self, path: Path, *, duration: float, settings: DetectorSettings
    ) -> list[Segment]:
        executable = find_tool(FFMPEG)
        if executable is None:
            raise ToolMissingError(FFMPEG, install_hint())

        filters: list[str] = []
        if settings.denoise_for_analysis:
            filters.append("afftdn=nf=-25")
        filters.append(
            f"silencedetect=noise={settings.threshold_db}dB:d={settings.min_silence}"
        )

        command = [
            executable,
            "-hide_banner",
            "-nostdin",
            "-v",
            "info",
            "-i",
            str(path),
            "-map",
            f"0:a:{0 if settings.audio_track is None else settings.audio_track}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-af",
            ",".join(filters),
            "-f",
            "null",
            "-",
        ]

        with tempfile.TemporaryFile() as errors:
            try:
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=errors,
                    stdin=subprocess.DEVNULL,
                )
            except OSError as exc:  # pragma: no cover - guarded by find_tool
                raise ProcessingError(f"cannot run ffmpeg: {exc}") from exc
            return_code = process.wait()
            errors.seek(0)
            output = errors.read().decode("utf-8", errors="replace")

        if return_code != 0:
            lowered = output.lower()
            if "stream map" in lowered or "does not contain any stream" in lowered:
                raise NoAudioStreamError(
                    f"{path} has no audio track on "
                    f"{0 if settings.audio_track is None else settings.audio_track}"
                )
            tail = (
                output.strip().splitlines()[-1] if output.strip() else "unknown error"
            )
            raise ProcessingError(f"silencedetect failed for {path}: {tail}")

        return invert_silences(
            parse_silencedetect(output, duration=duration), duration=duration
        )
