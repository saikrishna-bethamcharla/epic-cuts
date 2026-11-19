"""Shared post-processing order and edge cases (brief 3.2)."""

from __future__ import annotations

import pytest

from autocut.analysis.base import DetectorSettings, Segment
from autocut.analysis.postprocess import (
    apply_padding,
    cap_pauses,
    drop_short_segments,
    extend_to_bounds,
    merge_short_gaps,
    postprocess,
)

BASE = DetectorSettings(pad_before=0.0, pad_after=0.0, min_silence=0.5, min_speech=0.15)


def seg(start: float, end: float) -> Segment:
    return Segment(start=start, end=end)


def pairs(segments: list[Segment]) -> list[tuple[float, float]]:
    return [(round(item.start, 3), round(item.end, 3)) for item in segments]


def test_merge_short_gaps_joins_only_short_pauses() -> None:
    merged = merge_short_gaps(
        [seg(0.0, 1.0), seg(1.3, 2.0), seg(4.0, 5.0)], min_silence=0.5
    )
    assert pairs(merged) == [(0.0, 2.0), (4.0, 5.0)]


def test_drop_short_segments_removes_blips() -> None:
    kept = drop_short_segments([seg(0.0, 0.1), seg(1.0, 2.0)], min_speech=0.15)
    assert pairs(kept) == [(1.0, 2.0)]


def test_padding_is_clamped_and_merged() -> None:
    padded = apply_padding(
        [seg(0.0, 1.0), seg(1.05, 2.0)], duration=3.0, pad_before=0.2, pad_after=0.2
    )
    assert pairs(padded) == [(0.0, 2.2)]


def test_padding_never_exceeds_the_clip() -> None:
    padded = apply_padding([seg(1.0, 2.9)], duration=3.0, pad_before=0.5, pad_after=0.5)
    assert pairs(padded) == [(0.5, 3.0)]


def test_cap_pauses_keeps_only_the_target_silence() -> None:
    capped = cap_pauses(
        [seg(0.0, 1.0), seg(3.0, 4.0)],
        duration=5.0,
        target=0.3,
        trim_head_tail=True,
    )
    assert pairs(capped) == [(0.0, 1.3), (3.0, 4.0)]
    # 1.0-3.0 was a 2 s pause; only 0.3 s of it survives, so the cut removes 1.7 s.


def test_cap_pauses_also_caps_head_and_tail_unless_trimming() -> None:
    capped = cap_pauses(
        [seg(2.0, 3.0)], duration=10.0, target=0.3, trim_head_tail=False
    )
    assert pairs(capped) == [(1.7, 3.3)]


def test_cap_pauses_leaves_short_pauses_alone() -> None:
    capped = cap_pauses(
        [seg(0.0, 1.0), seg(1.2, 2.0)], duration=2.0, target=0.3, trim_head_tail=True
    )
    assert pairs(capped) == [(0.0, 1.0), (1.2, 2.0)]


def test_extend_to_bounds_keeps_head_and_tail_by_default() -> None:
    extended = extend_to_bounds([seg(2.0, 3.0)], duration=5.0, trim_head_tail=False)
    assert pairs(extended) == [(0.0, 5.0)]


def test_extend_to_bounds_respects_trimming() -> None:
    assert pairs(
        extend_to_bounds([seg(2.0, 3.0)], duration=5.0, trim_head_tail=True)
    ) == [(2.0, 3.0)]


def test_postprocess_applies_the_documented_order() -> None:
    """Merge short gaps, drop blips, then pad (padding must survive)."""
    settings = DetectorSettings(
        min_silence=0.5, min_speech=0.2, pad_before=0.1, pad_after=0.1
    )
    result = postprocess(
        [seg(0.0, 1.0), seg(1.2, 1.3), seg(5.0, 5.1), seg(5.15, 6.0)],
        duration=6.0,
        settings=settings,
    )
    # 1.2-1.3 merges into the first run; 5.0-5.1 is dropped as a blip before
    # padding; the survivor is padded to 4.9 and then reaches the clip end.
    assert pairs(result) == [(0.0, 1.4), (4.9, 6.0)]


def test_postprocess_of_nothing_is_nothing() -> None:
    assert postprocess([], duration=5.0, settings=BASE) == []


def test_postprocess_of_zero_length_clip_is_nothing() -> None:
    assert postprocess([seg(0.0, 1.0)], duration=0.0, settings=BASE) == []


def test_settings_reject_negative_values() -> None:
    with pytest.raises(ValueError, match="min_silence"):
        DetectorSettings(min_silence=-1.0)
    with pytest.raises(ValueError, match="min_speech"):
        DetectorSettings(min_speech=-1.0)
    with pytest.raises(ValueError, match="padding"):
        DetectorSettings(pad_before=-1.0)
    with pytest.raises(ValueError, match="shrink_pauses_to"):
        DetectorSettings(shrink_pauses_to=-1.0)


def test_segment_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="before start"):
        Segment(start=2.0, end=1.0)
