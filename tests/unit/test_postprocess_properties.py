"""Property tests for detection post-processing (brief section 8)."""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st

from autocut.analysis.base import DetectorSettings, Segment
from autocut.analysis.postprocess import postprocess

FLOAT = st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False)
PADDING = st.floats(min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False)


@hypothesis_settings(max_examples=150, deadline=None)
@given(
    duration=st.floats(
        min_value=0.2, max_value=60.0, allow_nan=False, allow_infinity=False
    ),
    raw=st.lists(st.tuples(FLOAT, FLOAT), max_size=8),
    min_silence=st.floats(
        min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
    ),
    min_speech=st.floats(
        min_value=0.0, max_value=0.5, allow_nan=False, allow_infinity=False
    ),
    pad_before=PADDING,
    pad_after=PADDING,
    shrink=st.one_of(st.none(), PADDING),
    trim=st.booleans(),
)
def test_postprocess_keeps_segments_sorted_bounded_and_within_the_source(
    duration: float,
    raw: list[tuple[float, float]],
    min_silence: float,
    min_speech: float,
    pad_before: float,
    pad_after: float,
    shrink: float | None,
    trim: bool,
) -> None:
    segments = [Segment(start=min(a, b), end=max(a, b)) for a, b in raw]
    settings = DetectorSettings(
        min_silence=min_silence,
        min_speech=min_speech,
        pad_before=pad_before,
        pad_after=pad_after,
        shrink_pauses_to=shrink,
        trim_head_tail=trim,
    )

    result = postprocess(segments, duration=duration, settings=settings)

    for previous, current in pairwise(result):
        assert current.start >= previous.end - 1e-9, "segments must not overlap"
    for segment in result:
        assert segment.start >= 0.0
        assert segment.end <= duration + 1e-9
        assert segment.end > segment.start
    assert sum(segment.duration for segment in result) <= duration + 1e-9
