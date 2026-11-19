"""One detector interface, shared settings, and the failures detectors can raise.

Both detectors return **keep segments** (speech to keep) in seconds. Everything
that happens afterwards — merging, dropping, padding, shrinking pauses — is
shared in :mod:`autocut.analysis.postprocess`, so the two backends cannot drift
apart in behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from autocut.errors import ProcessingError


class NoAudioStreamError(ProcessingError):
    """The selected audio track does not exist or cannot be decoded."""


class DetectorUnavailableError(ProcessingError):
    """The requested detector backend is not installed or has no model."""


@dataclass(frozen=True)
class Segment:
    """A half-open interval ``[start, end)`` in seconds."""

    start: float
    end: float

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"segment end {self.end} is before start {self.start}")

    @property
    def duration(self) -> float:
        return self.end - self.start

    def as_tuple(self) -> tuple[float, float]:
        return (self.start, self.end)


@dataclass(frozen=True)
class DetectorSettings:
    """Detection plus post-processing parameters (brief 3.2).

    ``min_speech`` doubles as the VAD's minimum speech duration: a second knob
    would only let the two stages disagree about what counts as speech.
    """

    threshold_db: float = -35.0
    min_silence: float = 0.5
    min_speech: float = 0.15
    speech_probability: float = 0.5
    pad_before: float = 0.18
    pad_after: float = 0.28
    shrink_pauses_to: float | None = None
    trim_head_tail: bool = False
    denoise_for_analysis: bool = False
    audio_track: int | None = None

    def __post_init__(self) -> None:
        if self.min_silence < 0:
            raise ValueError("min_silence must not be negative")
        if self.min_speech < 0:
            raise ValueError("min_speech must not be negative")
        if self.pad_before < 0 or self.pad_after < 0:
            raise ValueError("padding must not be negative")
        if self.shrink_pauses_to is not None and self.shrink_pauses_to < 0:
            raise ValueError("shrink_pauses_to must not be negative")

    def cache_key(self) -> dict[str, Any]:
        """The parameters that change detection output (not post-only padding)."""
        return {
            "threshold_db": self.threshold_db,
            "min_silence": self.min_silence,
            "min_speech": self.min_speech,
            "speech_probability": self.speech_probability,
            "denoise_for_analysis": self.denoise_for_analysis,
            "audio_track": self.audio_track,
            "pad_before": self.pad_before,
            "pad_after": self.pad_after,
            "shrink_pauses_to": self.shrink_pauses_to,
            "trim_head_tail": self.trim_head_tail,
        }


@runtime_checkable
class Detector(Protocol):
    """A silence/pause detector that returns keep segments in seconds."""

    name: str
    version: str

    def detect(
        self, path: Path, *, duration: float, settings: DetectorSettings
    ) -> list[Segment]:
        """Return the raw keep segments for one clip, before post-processing."""
        ...
