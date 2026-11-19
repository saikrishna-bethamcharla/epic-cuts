"""Cut List building: frames are canonical, seconds are derived."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from autocut.errors import InputError
from autocut.planning.cutlist import (
    ClipInput,
    SequenceFormat,
    build_cutlist,
    choose_sequence_format,
    write_cutlist,
)
from autocut.planning.timebase import Timebase

FPS_VALUES = ["24/1", "25/1", "30000/1001", "60000/1001", "50/1"]


def clip(
    name: str,
    *,
    fps: str = "25/1",
    duration: float = 10.0,
    segments: tuple[tuple[float, float], ...] = ((1.0, 3.0),),
    width: int | None = 1920,
    height: int | None = 1080,
) -> ClipInput:
    return ClipInput(
        path=Path(name),
        duration=duration,
        timebase=Timebase.parse(fps),
        segments=segments,
        width=width,
        height=height,
        source_hash="test-hash",
    )


def test_frames_are_canonical_and_seconds_derived() -> None:
    cutlist = build_cutlist(
        [clip("1.mp4", fps="25/1", duration=20.0, segments=((1.2, 14.85),))],
        settings={"detector": "energy"},
        created_at="2026-01-01T00:00:00Z",
    )
    segment = cutlist.clips[0].segments[0]
    assert segment.src_in_frame == 30
    assert segment.src_out_frame == 371
    assert segment.rec_in_frame == 0
    assert segment.rec_out_frame == 341

    payload = cutlist.to_json()
    segment_json = payload["clips"][0]["segments"][0]
    assert segment_json["frames"] == 341
    assert segment_json["src_in"] == pytest.approx(1.2)
    assert segment_json["src_out"] == pytest.approx(14.84)
    assert segment_json["rec_in"] == 0.0
    assert payload["sequence"]["fps"] == "25/1"
    assert payload["schema_version"] == 1


def test_rec_frames_are_contiguous_across_clips() -> None:
    clips = [
        clip("1.mp4", segments=((0.5, 1.5), (3.0, 4.0))),
        clip("2.mp4", segments=((2.0, 2.5),)),
    ]
    cutlist = build_cutlist(clips, settings={})
    segments = [segment for item in cutlist.clips for segment in item.segments]
    assert segments[0].rec_in_frame == 0
    for previous, current in pairwise(segments):
        assert current.rec_in_frame == previous.rec_out_frame
    assert cutlist.total_frames == sum(segment.frames for segment in segments)
    assert cutlist.total_frames == segments[-1].rec_out_frame


def test_markers_point_at_each_clip_start() -> None:
    cutlist = build_cutlist(
        [clip("intro.mp4", segments=((1.0, 2.0),)), clip("outro.mp4")], settings={}
    )
    first = cutlist.clips[0].markers[0]
    second = cutlist.clips[1].markers[0]
    assert first.name == "intro.mp4"
    assert first.at_frame == cutlist.clips[0].segments[0].rec_in_frame
    assert second.at_frame == cutlist.clips[1].segments[0].rec_in_frame


def test_segments_are_clamped_to_clip_bounds() -> None:
    cutlist = build_cutlist(
        [clip("1.mp4", duration=5.0, segments=((-2.0, 99.0),))], settings={}
    )
    segment = cutlist.clips[0].segments[0]
    assert segment.src_in_frame == 0
    assert segment.src_out_frame == 125


def test_empty_and_degenerate_segments_are_dropped() -> None:
    cutlist = build_cutlist(
        [clip("1.mp4", segments=((2.0, 2.0), (3.0, 3.019)))], settings={}
    )
    assert cutlist.clips[0].segments == ()
    assert cutlist.clips[0].markers == ()
    assert cutlist.total_frames == 0


def test_timeline_summary_reports_removed_percent() -> None:
    cutlist = build_cutlist(
        [clip("1.mp4", duration=10.0, segments=((0.0, 4.0),))], settings={}
    )
    payload = cutlist.to_json()["timeline"]
    assert payload["duration"] == pytest.approx(4.0)
    assert payload["source_duration"] == pytest.approx(10.0)
    assert payload["removed_duration"] == pytest.approx(6.0)
    assert payload["removed_percent"] == 60.0
    assert payload["cuts"] == 1


def test_sequence_format_uses_the_most_common_clip_format() -> None:
    clips = [
        clip("a.mp4", fps="25/1", width=1920, height=1080),
        clip("b.mp4", fps="30000/1001", width=3840, height=2160),
        clip("c.mp4", fps="30000/1001", width=3840, height=2160),
    ]
    sequence = choose_sequence_format(clips)
    assert str(sequence.timebase) == "30000/1001"
    assert (sequence.width, sequence.height) == (3840, 2160)


def test_explicit_sequence_overrides_the_default() -> None:
    cutlist = build_cutlist(
        [clip("1.mp4")],
        settings={},
        sequence=SequenceFormat(
            timebase=Timebase.parse("24/1"), width=1280, height=720
        ),
    )
    assert cutlist.sequence.width == 1280
    assert cutlist.to_json()["sequence"]["fps"] == "24/1"


def test_missing_clips_is_an_input_error() -> None:
    with pytest.raises(InputError, match="no clips"):
        build_cutlist([], settings={})


def test_write_cutlist_creates_folders(tmp_path: Path) -> None:
    cutlist = build_cutlist([clip("1.mp4")], settings={})
    target = write_cutlist(cutlist, tmp_path / "a" / "b" / "cutlist.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["clips"][0]["source_path"] == "1.mp4"
    assert payload["generator"]["name"] == "autocut"


@given(
    fps=st.sampled_from(FPS_VALUES),
    seq_fps=st.sampled_from(FPS_VALUES),
    raw_segments=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=20.0),
            st.floats(min_value=0.0, max_value=20.0),
        ),
        max_size=6,
    ),
)
@settings(max_examples=80, deadline=None)
def test_property_rec_frames_are_contiguous_and_total_matches_sum(
    fps: str, seq_fps: str, raw_segments: list[tuple[float, float]]
) -> None:
    ordered = sorted((min(a, b), max(a, b)) for a, b in raw_segments)
    clip_input = clip("1.mp4", fps=fps, duration=20.0, segments=tuple(ordered))
    cutlist = build_cutlist(
        [clip_input],
        settings={},
        sequence=SequenceFormat(timebase=Timebase.parse(seq_fps)),
    )
    timebase = cutlist.sequence.timebase

    segments = cutlist.clips[0].segments
    cursor = 0
    for segment in segments:
        assert segment.rec_in_frame == cursor
        assert segment.rec_out_frame > segment.rec_in_frame
        assert 0 <= segment.src_in_frame < segment.src_out_frame
        assert segment.src_out_frame <= cutlist.clips[0].duration_frames
        cursor = segment.rec_out_frame

    assert cutlist.total_frames == sum(segment.frames for segment in segments)
    assert cutlist.total_frames == cursor
    assert cutlist.duration == pytest.approx(timebase.seconds(cursor))
    # Conforming each cut to whole frames can add up to half a frame per segment;
    # everything else about the kept duration is bounded by the source.
    overshoot = 0.5 * max(len(segments), 1) / timebase.fps
    assert cutlist.duration <= cutlist.source_duration + overshoot + 1e-9

    payload = cutlist.to_json()["clips"][0]["segments"]
    for segment, raw in zip(segments, payload, strict=False):
        assert raw["rec_in_frame"] == segment.rec_in_frame
        assert raw["frames"] == segment.frames
        assert raw["rec_in"] == pytest.approx(
            round(timebase.seconds(segment.rec_in_frame), 6)
        )
