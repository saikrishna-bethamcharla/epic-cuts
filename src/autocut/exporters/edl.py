"""CMX 3600 EDL export.

One event per keep segment, in Cut List order. EDL is a single-rate format, so
mixed-rate sources are conformed to the sequence rate using the clip's own
timebase (``src_in`` seconds -> sequence frames); native frame positions are
preserved by the xmeml and FCPXML exporters instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from autocut.errors import InputError
from autocut.exporters.timecode import TimecodeFormat
from autocut.planning.loader import LoadedClip, LoadedCutList
from autocut.planning.timebase import Timebase

_INVALID_REEL = re.compile(r"[^A-Z0-9]")
_MAX_REEL = 8


@dataclass(frozen=True)
class EdlEvent:
    """One CMX event, with frame-exact source and record positions."""

    number: int
    reel: str
    source_in: int
    source_out: int
    record_in: int
    record_out: int
    clip: LoadedClip
    segment_index: int

    @property
    def duration(self) -> int:
        return self.record_out - self.record_in


def reel_names(clips: tuple[LoadedClip, ...]) -> dict[int, str]:
    """Short, unique, uppercase reel names derived from the source filenames."""
    names: dict[int, str] = {}
    used: set[str] = set()
    for clip in clips:
        stem = _INVALID_REEL.sub("", clip.source_path.stem.upper())[:_MAX_REEL] or "AX"
        candidate = stem
        suffix = 1
        while candidate in used:
            suffix += 1
            tail = str(suffix)
            candidate = f"{stem[: _MAX_REEL - len(tail)]}{tail}"
        used.add(candidate)
        names[clip.order] = candidate
    return names


def _conform(seconds: float, source: Timebase, sequence: Timebase) -> int:
    """A source position in seconds, expressed as a sequence frame."""
    if source == sequence:
        return round(seconds * sequence.num / sequence.den)
    return sequence.frames(seconds)


def build_events(cutlist: LoadedCutList) -> list[EdlEvent]:
    """Flatten the Cut List into ordered, frame-exact EDL events."""
    reels = reel_names(cutlist.clips)
    events: list[EdlEvent] = []
    for clip in cutlist.clips:
        for index, segment in enumerate(clip.segments):
            events.append(
                EdlEvent(
                    number=len(events) + 1,
                    reel=reels[clip.order],
                    source_in=_conform(
                        clip.timebase.seconds(segment.src_in_frame),
                        clip.timebase,
                        cutlist.timebase,
                    ),
                    source_out=_conform(
                        clip.timebase.seconds(segment.src_out_frame),
                        clip.timebase,
                        cutlist.timebase,
                    ),
                    record_in=segment.rec_in_frame,
                    record_out=segment.rec_out_frame,
                    clip=clip,
                    segment_index=index + 1,
                )
            )
    return events


def build_edl(
    cutlist: LoadedCutList,
    *,
    title: str | None = None,
    drop_frame: bool | None = None,
) -> str:
    """Render a complete CMX 3600 EDL as text."""
    events = build_events(cutlist)
    if not events:
        raise InputError("cut list has no segments to export")
    fmt = TimecodeFormat.for_timebase(cutlist.timebase, drop_frame=drop_frame)
    header = "DROP FRAME" if fmt.drop_frame else "NON-DROP FRAME"
    lines = [
        f"TITLE: {title or cutlist.title}",
        f"FCM: {header}",
        "",
    ]
    for event in events:
        lines.append(
            f"{event.number:03d}  {event.reel:<8} {'AA/V':<5} C        "
            f"{fmt.timecode(event.source_in)} {fmt.timecode(event.source_out)} "
            f"{fmt.timecode(event.record_in)} {fmt.timecode(event.record_out)}"
        )
        lines.append(f"* FROM CLIP NAME: {event.clip.source_path.name}")
        lines.append(
            f"* AUTOCUT SEGMENT: clip {event.clip.order} "
            f"segment {event.segment_index}/{len(event.clip.segments)}"
        )
        if event.clip.audio_stream is None:
            lines.append("* NO AUDIO IN SOURCE")
        lines.append("")
    return "\n".join(lines)
