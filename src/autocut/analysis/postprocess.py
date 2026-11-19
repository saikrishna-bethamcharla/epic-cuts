"""Shared keep-segment post-processing, in the order the brief fixes.

1. merge keep segments separated by a gap shorter than ``min_silence``
2. drop keep segments shorter than ``min_speech`` (clicks, coughs)
3. pad each segment, clamped to the clip, then re-merge overlaps
4. optionally cap every pause (``shrink_pauses_to``) instead of deleting it
5. optionally trim the head and tail of the clip

Doing this once, here, is what keeps the energy and VAD detectors comparable:
each detector only has to produce raw speech runs.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from autocut.analysis.base import DetectorSettings, Segment

LOGGER = logging.getLogger(__name__)


def _normalise(segments: Sequence[Segment], *, duration: float) -> list[Segment]:
    """Clamp, drop empties, sort and merge touching or overlapping runs."""
    clamped: list[Segment] = []
    for segment in segments:
        start = max(0.0, min(segment.start, duration))
        end = max(0.0, min(segment.end, duration))
        if end > start:
            clamped.append(Segment(start=start, end=end))
    clamped.sort(key=lambda item: item.start)
    merged: list[Segment] = []
    for segment in clamped:
        if merged and segment.start <= merged[-1].end:
            if segment.end > merged[-1].end:
                merged[-1] = Segment(start=merged[-1].start, end=segment.end)
        else:
            merged.append(segment)
    return merged


def merge_short_gaps(
    segments: Sequence[Segment], *, min_silence: float
) -> list[Segment]:
    """Join keep segments whose separating pause is shorter than ``min_silence``."""
    merged: list[Segment] = []
    for segment in segments:
        if merged and segment.start - merged[-1].end < min_silence:
            merged[-1] = Segment(start=merged[-1].start, end=segment.end)
        else:
            merged.append(segment)
    return merged


def drop_short_segments(
    segments: Sequence[Segment], *, min_speech: float
) -> list[Segment]:
    """Remove blips shorter than ``min_speech``."""
    return [segment for segment in segments if segment.duration >= min_speech]


def apply_padding(
    segments: Sequence[Segment],
    *,
    duration: float,
    pad_before: float,
    pad_after: float,
) -> list[Segment]:
    """Extend each segment, clamp to the clip, then merge the new overlaps."""
    padded = [
        Segment(
            start=max(0.0, segment.start - pad_before),
            end=min(duration, segment.end + pad_after),
        )
        for segment in segments
    ]
    return _normalise(padded, duration=duration)


def cap_pauses(
    segments: Sequence[Segment], *, duration: float, target: float, trim_head_tail: bool
) -> list[Segment]:
    """Shorten every pause to ``target`` seconds instead of removing it entirely."""
    if not segments:
        return []
    capped = list(segments)
    for index in range(1, len(capped)):
        previous = capped[index - 1]
        gap = capped[index].start - previous.end
        if gap > target:
            # Keep ``target`` seconds of the pause, drop the rest.
            capped[index - 1] = Segment(
                start=previous.start,
                end=min(capped[index].start, previous.end + target),
            )
    if not trim_head_tail:
        first = capped[0]
        capped[0] = Segment(start=max(0.0, first.start - target), end=first.end)
        last = capped[-1]
        clamped_end = min(duration, last.end + target)
        capped[-1] = Segment(start=last.start, end=clamped_end)
    return [segment for segment in capped if segment.duration > 0]


def extend_to_bounds(
    segments: Sequence[Segment], *, duration: float, trim_head_tail: bool
) -> list[Segment]:
    """By default the clip's head and tail are kept; trimming them is opt-in."""
    if not segments or trim_head_tail:
        return list(segments)
    extended = list(segments)
    extended[0] = Segment(start=0.0, end=extended[0].end)
    extended[-1] = Segment(start=extended[-1].start, end=duration)
    return extended


def postprocess(
    segments: Sequence[Segment], *, duration: float, settings: DetectorSettings
) -> list[Segment]:
    """Apply every shared rule to one clip's raw keep segments."""
    if duration <= 0:
        return []

    working = _normalise(segments, duration=duration)
    working = merge_short_gaps(working, min_silence=settings.min_silence)
    working = drop_short_segments(working, min_speech=settings.min_speech)
    working = apply_padding(
        working,
        duration=duration,
        pad_before=settings.pad_before,
        pad_after=settings.pad_after,
    )
    if settings.shrink_pauses_to is not None:
        working = cap_pauses(
            working,
            duration=duration,
            target=settings.shrink_pauses_to,
            trim_head_tail=settings.trim_head_tail,
        )
    working = extend_to_bounds(
        working, duration=duration, trim_head_tail=settings.trim_head_tail
    )
    working = _normalise(working, duration=duration)
    LOGGER.debug(
        "postprocess: %d in, %d out, %.2fs kept of %.2fs",
        len(segments),
        len(working),
        sum(segment.duration for segment in working),
        duration,
    )
    return working
