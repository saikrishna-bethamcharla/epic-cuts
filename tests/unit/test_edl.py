"""SMPTE timecode and CMX 3600 EDL export."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.exporters.edl import build_edl, build_events, reel_names
from autocut.exporters.timecode import TimecodeFormat
from autocut.planning.loader import load_cutlist
from autocut.planning.timebase import Timebase
from tests.cutlist_factory import cutlist_payload, write_cutlist

NTSC = Timebase.parse("30000/1001")
EVENT_LINE = re.compile(
    r"^\d{3}  \S+\s+AA/V\s+C\s+"
    r"(\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d) "
    r"(\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d)$"
)


def test_non_drop_frame_roundtrip() -> None:
    fmt = TimecodeFormat.for_timebase(Timebase.parse("25/1"))
    assert fmt.drop_frame is False
    for frame in (0, 1, 24, 25, 1501, 90_000):
        assert fmt.frame_number(fmt.timecode(frame)) == frame
    assert fmt.timecode(1501) == "00:01:00:01"


def test_drop_frame_labels_and_roundtrip() -> None:
    fmt = TimecodeFormat.for_timebase(NTSC)
    assert fmt.drop_frame is True
    assert fmt.nominal == 30
    assert fmt.timecode(1799) == "00:00:59:29"
    assert fmt.timecode(1800) == "00:01:00:02"
    assert fmt.timecode(17_982) == "00:10:00:00"
    assert fmt.timecode(17_983) == "00:10:00:01"
    for frame in (0, 29, 1799, 1800, 3600, 17_982, 17_983, 107_892, 200_000):
        assert fmt.frame_number(fmt.timecode(frame)) == frame


def test_drop_frame_is_refused_at_25fps() -> None:
    with pytest.raises(InputError, match="drop-frame"):
        TimecodeFormat(nominal=25, drop_frame=True)


def test_timecode_rejects_garbage() -> None:
    fmt = TimecodeFormat.for_timebase(Timebase.parse("25/1"))
    with pytest.raises(InputError, match="invalid timecode"):
        fmt.frame_number("00:00:00")
    with pytest.raises(InputError, match="out of range"):
        fmt.frame_number("00:00:00:25")
    with pytest.raises(InputError, match="negative"):
        fmt.timecode(-1)


def test_events_are_contiguous_and_cover_every_segment(tmp_path: Path) -> None:
    loaded = load_cutlist(write_cutlist(tmp_path))
    events = build_events(loaded)

    assert len(events) == 3
    assert [event.number for event in events] == [1, 2, 3]
    assert events[0].source_in == 0
    assert events[0].source_out == 50
    assert events[1].record_in == events[0].record_out
    assert sum(event.duration for event in events) == loaded.total_frames
    assert len({event.reel for event in events}) == 2


def test_reels_are_short_uppercase_and_unique(tmp_path: Path) -> None:
    payload = cutlist_payload(
        clips=[
            {
                "order": 1,
                "source_path": "a/first clip & take.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "segments": [(0, 50)],
            },
            {
                "order": 2,
                "source_path": "b/firstclip&take.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "segments": [(0, 50)],
            },
        ]
    )
    loaded = load_cutlist(write_cutlist(tmp_path, payload))
    names = reel_names(loaded.clips)
    assert all(len(name) <= 8 and name.isalnum() for name in names.values())
    assert len(set(names.values())) == 2


def test_edl_text_uses_drop_frame_at_ntsc(tmp_path: Path) -> None:
    payload = cutlist_payload(fps="30000/1001")
    loaded = load_cutlist(write_cutlist(tmp_path, payload))
    text = build_edl(loaded)

    assert text.startswith("TITLE: cutlist\nFCM: DROP FRAME\n")
    lines = [line for line in text.splitlines() if EVENT_LINE.match(line)]
    assert len(lines) == 3
    assert "* FROM CLIP NAME: 01.mp4" in text
    assert "* AUTOCUT SEGMENT: clip 1 segment 1/2" in text

    fmt = TimecodeFormat.for_timebase(loaded.timebase)
    for line in lines:
        match = EVENT_LINE.match(line)
        assert match is not None
        record_in, record_out = (
            fmt.frame_number(match.group(3)),
            fmt.frame_number(match.group(4)),
        )
        assert record_out > record_in


def test_edl_can_force_non_drop_frame(tmp_path: Path) -> None:
    payload = cutlist_payload(fps="30000/1001")
    loaded = load_cutlist(write_cutlist(tmp_path, payload))
    text = build_edl(loaded, drop_frame=False, title="My Assembly")
    assert text.startswith("TITLE: My Assembly\nFCM: NON-DROP FRAME\n")


def test_mixed_rate_sources_are_conformed_to_the_sequence(tmp_path: Path) -> None:
    payload = cutlist_payload(
        fps="30000/1001",
        clips=[
            {
                "order": 1,
                "source_path": "pals/01.mp4",
                "duration_frames": 250,
                "fps": "25/1",
                "segments": [(25, 50)],
            }
        ],
    )
    loaded = load_cutlist(write_cutlist(tmp_path, payload))
    event = build_events(loaded)[0]
    # 1.0 s at 25 fps is 30 frames at 29.97 fps.
    assert event.source_in == 30
    assert event.source_out == 60
