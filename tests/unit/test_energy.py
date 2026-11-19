"""silencedetect parsing and silence inversion."""

from __future__ import annotations

from autocut.analysis.energy import invert_silences, parse_silencedetect

SAMPLE = """
[silencedetect @ 000001] silence_start: 1.000
[silencedetect @ 000001] silence_end: 2.000 | silence_duration: 1.000
[silencedetect @ 000001] silence_start: 4.500
[silencedetect @ 000001] silence_end: 5.250 | silence_duration: 0.750
"""


def test_parse_pairs_start_and_end() -> None:
    silences = parse_silencedetect(SAMPLE, duration=6.0)
    assert [(item.start, item.end) for item in silences] == [(1.0, 2.0), (4.5, 5.25)]


def test_unmatched_start_closes_at_the_clip_end() -> None:
    silences = parse_silencedetect("silence_start: 3.0", duration=4.0)
    assert [(item.start, item.end) for item in silences] == [(3.0, 4.0)]


def test_end_beyond_duration_is_clamped() -> None:
    silences = parse_silencedetect(
        "silence_start: 3.0\nsilence_end: 9.0 | silence_duration: 6.0", duration=4.0
    )
    assert [(item.start, item.end) for item in silences] == [(3.0, 4.0)]


def test_garbage_is_ignored() -> None:
    assert parse_silencedetect("random log line\nanother", duration=5.0) == []
    assert parse_silencedetect("", duration=5.0) == []


def test_invert_turns_silences_into_keep_segments() -> None:
    silences = parse_silencedetect(SAMPLE, duration=6.0)
    keep = invert_silences(silences, duration=6.0)
    assert [(round(s.start, 3), round(s.end, 3)) for s in keep] == [
        (0.0, 1.0),
        (2.0, 4.5),
        (5.25, 6.0),
    ]


def test_invert_with_leading_silence_starts_after_it() -> None:
    keep = invert_silences(
        parse_silencedetect("silence_start: 0.0\nsilence_end: 1.0", duration=3.0),
        duration=3.0,
    )
    assert [(round(s.start, 3), round(s.end, 3)) for s in keep] == [(1.0, 3.0)]


def test_invert_of_entirely_silent_clip_is_empty() -> None:
    keep = invert_silences(
        parse_silencedetect("silence_start: 0.0\nsilence_end: 3.0", duration=3.0),
        duration=3.0,
    )
    assert keep == []


def test_invert_without_silences_keeps_everything() -> None:
    keep = invert_silences([], duration=3.0)
    assert [(round(s.start, 3), round(s.end, 3)) for s in keep] == [(0.0, 3.0)]
