"""Build the Cut List (schema version 1) from per-clip keep segments.

Frames are canonical. A segment stores ``src_*_frame`` in the clip's own
timebase and ``rec_*_frame`` on the assembled sequence; every seconds value in
the JSON is derived from those integers, so a long assembly cannot drift.

The builder is deliberately independent of discovery and detection: it takes
plain :class:`ClipInput` values, which makes it trivial to test at any frame rate.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from autocut import __version__
from autocut.errors import InputError
from autocut.media.fingerprint import file_fingerprint
from autocut.planning.timebase import Timebase

LOGGER = logging.getLogger(__name__)

CUTLIST_SCHEMA_VERSION = 1
DEFAULT_AUDIO_RATE = 48000
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
_SECONDS_PRECISION = 6


@dataclass(frozen=True)
class SequenceFormat:
    """The format the assembled timeline is conformed to."""

    timebase: Timebase
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    audio_rate: int = DEFAULT_AUDIO_RATE

    def to_json(self) -> dict[str, Any]:
        return {
            "fps": str(self.timebase),
            "width": self.width,
            "height": self.height,
            "audio_rate": self.audio_rate,
            "frame_rounding": "nearest",
        }


@dataclass(frozen=True)
class ClipInput:
    """One source clip and the keep segments detection produced for it."""

    path: Path
    duration: float
    timebase: Timebase
    segments: tuple[tuple[float, float], ...] = ()
    width: int | None = None
    height: int | None = None
    audio_stream: int | None = None
    warnings: tuple[str, ...] = ()
    source_hash: str | None = None


@dataclass(frozen=True)
class CutSegment:
    """A keep segment, in source frames and assembled-timeline frames."""

    src_in_frame: int
    src_out_frame: int
    rec_in_frame: int
    rec_out_frame: int

    @property
    def frames(self) -> int:
        return self.rec_out_frame - self.rec_in_frame

    @property
    def src_frames(self) -> int:
        return self.src_out_frame - self.src_in_frame


@dataclass(frozen=True)
class Marker:
    """Navigation marker on the assembled timeline."""

    at_frame: int
    name: str


@dataclass(frozen=True)
class CutClip:
    """One clip as it appears in the Cut List."""

    order: int
    source_path: Path
    source_hash: str
    duration_frames: int
    timebase: Timebase
    segments: tuple[CutSegment, ...]
    width: int | None = None
    height: int | None = None
    audio_stream: int | None = None
    warnings: tuple[str, ...] = ()
    markers: tuple[Marker, ...] = ()

    @property
    def kept_frames(self) -> int:
        return sum(segment.frames for segment in self.segments)

    def to_json(self, sequence: SequenceFormat) -> dict[str, Any]:
        clip_tb = self.timebase
        seq_tb = sequence.timebase
        return {
            "order": self.order,
            "source_path": str(self.source_path),
            "source_hash": self.source_hash,
            "duration_frames": self.duration_frames,
            "duration": round(
                clip_tb.seconds(self.duration_frames), _SECONDS_PRECISION
            ),
            "fps": str(clip_tb),
            "width": self.width,
            "height": self.height,
            "audio_stream": self.audio_stream,
            "warnings": list(self.warnings),
            "segments": [
                {
                    "src_in_frame": segment.src_in_frame,
                    "src_out_frame": segment.src_out_frame,
                    "rec_in_frame": segment.rec_in_frame,
                    "rec_out_frame": segment.rec_out_frame,
                    "frames": segment.frames,
                    "src_in": round(
                        clip_tb.seconds(segment.src_in_frame), _SECONDS_PRECISION
                    ),
                    "src_out": round(
                        clip_tb.seconds(segment.src_out_frame), _SECONDS_PRECISION
                    ),
                    "rec_in": round(
                        seq_tb.seconds(segment.rec_in_frame), _SECONDS_PRECISION
                    ),
                    "rec_out": round(
                        seq_tb.seconds(segment.rec_out_frame), _SECONDS_PRECISION
                    ),
                }
                for segment in self.segments
            ],
            "markers": [
                {
                    "at_frame": marker.at_frame,
                    "at": round(seq_tb.seconds(marker.at_frame), _SECONDS_PRECISION),
                    "name": marker.name,
                }
                for marker in self.markers
            ],
        }


@dataclass(frozen=True)
class CutList:
    """The canonical, non-destructive description of the assembly."""

    clips: tuple[CutClip, ...]
    sequence: SequenceFormat
    settings: dict[str, Any]
    created_at: str
    schema_version: int = CUTLIST_SCHEMA_VERSION

    @property
    def total_frames(self) -> int:
        return sum(clip.kept_frames for clip in self.clips)

    @property
    def cut_count(self) -> int:
        return sum(len(clip.segments) for clip in self.clips)

    @property
    def source_duration(self) -> float:
        return sum(clip.timebase.seconds(clip.duration_frames) for clip in self.clips)

    @property
    def duration(self) -> float:
        return self.sequence.timebase.seconds(self.total_frames)

    @property
    def removed_duration(self) -> float:
        return max(0.0, self.source_duration - self.duration)

    @property
    def removed_percent(self) -> float:
        if self.source_duration <= 0:
            return 0.0
        return round(self.removed_duration / self.source_duration * 100.0, 1)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "generator": {"name": "autocut", "version": __version__},
            "settings": self.settings,
            "sequence": self.sequence.to_json(),
            "clips": [clip.to_json(self.sequence) for clip in self.clips],
            "timeline": {
                "frames": self.total_frames,
                "duration": round(self.duration, _SECONDS_PRECISION),
                "cuts": self.cut_count,
                "source_duration": round(self.source_duration, _SECONDS_PRECISION),
                "removed_duration": round(self.removed_duration, _SECONDS_PRECISION),
                "removed_percent": self.removed_percent,
            },
        }


def _most_common(values: Sequence[Any], default: Any) -> Any:
    if not values:
        return default
    return Counter(values).most_common(1)[0][0]


def choose_sequence_format(clips: Sequence[ClipInput]) -> SequenceFormat:
    """The most common format among the clips, per brief 3.3."""
    timebases = [clip.timebase for clip in clips]
    formats = [
        (clip.width, clip.height)
        for clip in clips
        if clip.width is not None and clip.height is not None
    ]
    chosen_timebase = _most_common([str(tb) for tb in timebases], "25/1")
    width_height = _most_common(formats, (DEFAULT_WIDTH, DEFAULT_HEIGHT))
    return SequenceFormat(
        timebase=Timebase.parse(chosen_timebase),
        width=width_height[0],
        height=width_height[1],
        audio_rate=DEFAULT_AUDIO_RATE,
    )


def _now() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _merge_overlaps(
    segments: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Sort and merge touching/overlapping keep segments.

    Detection already returns ordered, non-overlapping segments; merging here
    keeps the "kept duration never exceeds source duration" invariant true even
    for hand-edited or partially overlapping input (review UI, M7).
    """
    ordered = sorted((min(start, end), max(start, end)) for start, end in segments)
    merged: list[list[float]] = []
    for start, end in ordered:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(start, end) for start, end in merged]


def build_cutlist(
    clips: Sequence[ClipInput],
    *,
    settings: dict[str, Any],
    sequence: SequenceFormat | None = None,
    full_hash: bool = False,
    created_at: str | None = None,
) -> CutList:
    """Conform every keep segment to whole frames and assemble the timeline."""
    if not clips:
        raise InputError("no clips to build a cut list from")

    sequence = sequence or choose_sequence_format(clips)
    seq_tb = sequence.timebase
    cursor = 0
    built: list[CutClip] = []

    for order, clip in enumerate(clips, start=1):
        clip_tb = clip.timebase
        duration_frames = clip_tb.frames(clip.duration)
        segments: list[CutSegment] = []

        for start, end in _merge_overlaps(clip.segments):
            src_in = max(0, min(clip_tb.frames(start), duration_frames))
            src_out = max(0, min(clip_tb.frames(end), duration_frames))
            if src_out <= src_in:
                LOGGER.debug(
                    "dropping empty segment %.3f-%.3f in %s", start, end, clip.path
                )
                continue
            kept_seconds = clip_tb.seconds(src_out - src_in)
            rec_frames = max(1, seq_tb.frames(kept_seconds))
            segments.append(
                CutSegment(
                    src_in_frame=src_in,
                    src_out_frame=src_out,
                    rec_in_frame=cursor,
                    rec_out_frame=cursor + rec_frames,
                )
            )
            cursor += rec_frames

        markers: tuple[Marker, ...] = ()
        if segments:
            markers = (Marker(at_frame=segments[0].rec_in_frame, name=clip.path.name),)

        built.append(
            CutClip(
                order=order,
                source_path=clip.path,
                source_hash=(
                    clip.source_hash
                    if clip.source_hash is not None
                    else file_fingerprint(clip.path, full_hash=full_hash)
                ),
                duration_frames=duration_frames,
                timebase=clip_tb,
                segments=tuple(segments),
                width=clip.width,
                height=clip.height,
                audio_stream=clip.audio_stream,
                warnings=clip.warnings,
                markers=markers,
            )
        )

    return CutList(
        clips=tuple(built),
        sequence=sequence,
        settings=dict(settings),
        created_at=created_at or _now(),
    )


def write_cutlist(cutlist: CutList, path: Path) -> Path:
    """Serialise a Cut List, creating parent folders as needed."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(cutlist.to_json(), indent=2, ensure_ascii=False)
    target.write_text(payload + "\n", encoding="utf-8")
    return target
