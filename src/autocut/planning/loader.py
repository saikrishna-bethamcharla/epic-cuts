"""Read and validate a Cut List written by an earlier AutoCut run.

Exporters and the renderer never rebuild a timeline: they consume the JSON
document described in ``docs/CUTLIST_SPEC.md``. Loading validates the frame
invariants up front so an exporter cannot silently emit a broken timeline from a
hand-edited or truncated file, and it resolves relative ``source_path`` values
against the Cut List's own folder so a project can be moved as a unit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocut.errors import InputError
from autocut.planning.cutlist import CUTLIST_SCHEMA_VERSION
from autocut.planning.timebase import Timebase


@dataclass(frozen=True)
class LoadedSegment:
    """A keep segment, in source frames and assembled-timeline frames."""

    src_in_frame: int
    src_out_frame: int
    rec_in_frame: int
    rec_out_frame: int

    @property
    def frames(self) -> int:
        return self.rec_out_frame - self.rec_in_frame


@dataclass(frozen=True)
class LoadedMarker:
    at_frame: int
    name: str


@dataclass(frozen=True)
class LoadedClip:
    """One clip of a loaded Cut List, with its source path already resolved."""

    order: int
    source_path: Path
    source_hash: str
    duration_frames: int
    timebase: Timebase
    segments: tuple[LoadedSegment, ...]
    width: int | None = None
    height: int | None = None
    audio_stream: int | None = None
    warnings: tuple[str, ...] = ()
    markers: tuple[LoadedMarker, ...] = ()

    @property
    def kept_frames(self) -> int:
        return sum(segment.frames for segment in self.segments)


@dataclass(frozen=True)
class LoadedCutList:
    """A validated Cut List, ready for an exporter or the renderer."""

    path: Path
    schema_version: int
    created_at: str | None
    generator: dict[str, Any]
    settings: dict[str, Any]
    timebase: Timebase
    width: int
    height: int
    audio_rate: int
    clips: tuple[LoadedClip, ...]

    @property
    def title(self) -> str:
        return self.path.stem

    @property
    def total_frames(self) -> int:
        return sum(clip.kept_frames for clip in self.clips)

    @property
    def duration_seconds(self) -> float:
        return self.timebase.seconds(self.total_frames)

    @property
    def has_audio(self) -> bool:
        return any(clip.audio_stream is not None for clip in self.clips)

    def missing_sources(self) -> tuple[Path, ...]:
        """Source files referenced by the Cut List that are not on disk."""
        return tuple(
            dict.fromkeys(
                clip.source_path for clip in self.clips if not clip.source_path.exists()
            )
        )


def _mapping(value: object, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise InputError(f"cut list {where} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _integer(payload: dict[str, Any], key: str, where: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"cut list {where}.{key} must be an integer")
    return value


def _optional_integer(payload: dict[str, Any], key: str, where: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError(f"cut list {where}.{key} must be an integer or null")
    return value


def _string(payload: dict[str, Any], key: str, where: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise InputError(f"cut list {where}.{key} must be a non-empty string")
    return value


def _optional_string_list(
    payload: dict[str, Any], key: str, where: str
) -> tuple[str, ...]:
    value = payload.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InputError(f"cut list {where}.{key} must be a list of strings")
    return tuple(value)


def _sequence_fps(payload: dict[str, Any]) -> Timebase:
    raw = payload.get("fps")
    if isinstance(raw, str):
        return Timebase.parse(raw)
    if isinstance(raw, int) and not isinstance(raw, bool):
        return Timebase.parse(raw)
    raise InputError(
        "cut list sequence.fps must be a rational string such as '30000/1001'"
    )


def _source_path(raw: str, base: Path) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _load_segments(
    payload: dict[str, Any], where: str, duration_frames: int
) -> tuple[LoadedSegment, ...]:
    raw = payload.get("segments", [])
    if not isinstance(raw, list):
        raise InputError(f"cut list {where}.segments must be a list")

    segments: list[LoadedSegment] = []
    cursor: int | None = None
    for index, item in enumerate(raw):
        entry = _mapping(item, f"{where}.segments[{index}]")
        src_in = _integer(entry, "src_in_frame", f"{where}.segments[{index}]")
        src_out = _integer(entry, "src_out_frame", f"{where}.segments[{index}]")
        rec_in = _integer(entry, "rec_in_frame", f"{where}.segments[{index}]")
        rec_out = _integer(entry, "rec_out_frame", f"{where}.segments[{index}]")
        if not 0 <= src_in < src_out <= duration_frames:
            raise InputError(
                f"cut list {where}.segments[{index}] is outside the source: "
                f"{src_in}..{src_out} of {duration_frames} frames"
            )
        if cursor is not None and rec_in != cursor:
            raise InputError(
                f"cut list {where}.segments[{index}] starts at frame {rec_in} "
                f"but the previous segment ended at {cursor}; the recording "
                "timeline must be contiguous"
            )
        if rec_out <= rec_in:
            raise InputError(
                f"cut list {where}.segments[{index}] has no duration on the timeline"
            )
        segments.append(
            LoadedSegment(
                src_in_frame=src_in,
                src_out_frame=src_out,
                rec_in_frame=rec_in,
                rec_out_frame=rec_out,
            )
        )
        cursor = rec_out
    return tuple(segments)


def _load_markers(payload: dict[str, Any], where: str) -> tuple[LoadedMarker, ...]:
    raw = payload.get("markers", [])
    if not isinstance(raw, list):
        raise InputError(f"cut list {where}.markers must be a list")
    markers: list[LoadedMarker] = []
    for index, item in enumerate(raw):
        entry = _mapping(item, f"{where}.markers[{index}]")
        markers.append(
            LoadedMarker(
                at_frame=_integer(entry, "at_frame", f"{where}.markers[{index}]"),
                name=_string(entry, "name", f"{where}.markers[{index}]"),
            )
        )
    return tuple(markers)


def parse_cutlist(payload: dict[str, Any], path: Path) -> LoadedCutList:
    """Validate an already-parsed Cut List document."""
    schema_version = payload.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise InputError("cut list has no integer schema_version")
    if schema_version > CUTLIST_SCHEMA_VERSION:
        raise InputError(
            f"cut list schema_version {schema_version} is newer than this build "
            f"supports ({CUTLIST_SCHEMA_VERSION}); upgrade AutoCut"
        )
    if schema_version < 1:
        raise InputError(f"cut list schema_version {schema_version} is not valid")

    sequence = _mapping(payload.get("sequence"), "sequence")
    timebase = _sequence_fps(sequence)
    width = _optional_integer(sequence, "width", "sequence") or 1920
    height = _optional_integer(sequence, "height", "sequence") or 1080
    audio_rate = _optional_integer(sequence, "audio_rate", "sequence") or 48000
    if width <= 0 or height <= 0 or audio_rate <= 0:
        raise InputError("cut list sequence dimensions and audio rate must be positive")

    raw_clips = payload.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise InputError("cut list has no clips")

    base = path.parent
    clips: list[LoadedClip] = []
    timeline_cursor = 0
    for index, item in enumerate(raw_clips):
        where = f"clips[{index}]"
        entry = _mapping(item, where)
        clip_timebase = Timebase.parse(
            entry["fps"] if isinstance(entry.get("fps"), str) else str(entry.get("fps"))
        )
        duration_frames = _integer(entry, "duration_frames", where)
        if duration_frames <= 0:
            raise InputError(f"cut list {where}.duration_frames must be positive")
        segments = _load_segments(entry, where, duration_frames)
        if segments:
            if segments[0].rec_in_frame != timeline_cursor:
                raise InputError(
                    f"cut list {where} starts at frame {segments[0].rec_in_frame} "
                    f"but the previous clip ended at {timeline_cursor}; the "
                    "recording timeline must be contiguous"
                )
            timeline_cursor = segments[-1].rec_out_frame
        clips.append(
            LoadedClip(
                order=_optional_integer(entry, "order", where) or index + 1,
                source_path=_source_path(_string(entry, "source_path", where), base),
                source_hash=str(entry.get("source_hash") or ""),
                duration_frames=duration_frames,
                timebase=clip_timebase,
                segments=segments,
                width=_optional_integer(entry, "width", where),
                height=_optional_integer(entry, "height", where),
                audio_stream=_optional_integer(entry, "audio_stream", where),
                warnings=_optional_string_list(entry, "warnings", where),
                markers=_load_markers(entry, where),
            )
        )

    generator = payload.get("generator")
    settings = payload.get("settings")
    return LoadedCutList(
        path=path,
        schema_version=schema_version,
        created_at=payload.get("created_at")
        if isinstance(payload.get("created_at"), str)
        else None,
        generator=_mapping(generator, "generator") if generator is not None else {},
        settings=_mapping(settings, "settings") if settings is not None else {},
        timebase=timebase,
        width=width,
        height=height,
        audio_rate=audio_rate,
        clips=tuple(clips),
    )


def load_cutlist(path: Path) -> LoadedCutList:
    """Read a Cut List JSON file, raising :class:`InputError` when it is invalid."""
    source = Path(path).expanduser()
    if not source.exists():
        raise InputError(f"cut list does not exist: {source}")
    if not source.is_file():
        raise InputError(f"cut list path is not a file: {source}")
    try:
        raw: object = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read cut list {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"cut list {source} is not valid JSON: {exc}") from exc
    payload = _mapping(raw, "document")
    return parse_cutlist(payload, source.resolve())


@dataclass(frozen=True)
class CutListSummary:
    """The numbers a CLI prints after loading a Cut List."""

    clips: int
    cuts: int
    frames: int
    duration: float
    missing_sources: tuple[Path, ...]

    @classmethod
    def of(cls, cutlist: LoadedCutList) -> CutListSummary:
        return cls(
            clips=len(cutlist.clips),
            cuts=sum(len(clip.segments) for clip in cutlist.clips),
            frames=cutlist.total_frames,
            duration=cutlist.duration_seconds,
            missing_sources=cutlist.missing_sources(),
        )
