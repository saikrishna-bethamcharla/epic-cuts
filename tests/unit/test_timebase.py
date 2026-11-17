"""Frame-accurate timebase maths."""

from __future__ import annotations

import pytest

from autocut.errors import InputError
from autocut.planning.timebase import Timebase

FPS_VALUES = ["24/1", "25/1", "30000/1001", "60000/1001", "50/1"]


@pytest.mark.parametrize("fps", FPS_VALUES)
def test_frame_indices_round_trip_at_common_rates(fps: str) -> None:
    timebase = Timebase.parse(fps)
    for frames in (0, 1, 2, 23, 24, 25, 100, 1000, 5000):
        seconds = timebase.seconds(frames)
        assert timebase.frames(seconds) == frames


def test_parse_accepts_rationals_and_whole_numbers() -> None:
    assert str(Timebase.parse("30000/1001")) == "30000/1001"
    assert str(Timebase.parse("25")) == "25/1"
    assert Timebase.parse("25").fps == 25.0
    assert Timebase.parse(50).num == 50
    assert Timebase.parse(24.0).den == 1


@pytest.mark.parametrize("bad", ["abc", "0/1", "-25", ""])
def test_parse_rejects_invalid_rates(bad: str) -> None:
    with pytest.raises(InputError):
        Timebase.parse(bad)


def test_construction_rejects_zero_denominator() -> None:
    with pytest.raises(InputError, match="invalid timebase"):
        Timebase(num=25, den=0)


def test_rounding_is_half_up() -> None:
    timebase = Timebase.parse("25")
    assert timebase.frames(0.0199) == 0
    assert timebase.frames(0.0201) == 1
    assert timebase.frames(0.02) == 1  # exactly half a frame rounds up
    assert timebase.frames(-1.0) == 0


def test_ntsc_rates_are_not_floats() -> None:
    ntsc = Timebase.parse("30000/1001")
    assert ntsc.fps != 30.0
    assert abs(ntsc.seconds(30000) - 1001.0) < 1e-9


def test_seconds_are_derived_from_frames() -> None:
    timebase = Timebase.parse("24/1")
    assert timebase.seconds(48) == pytest.approx(2.0)
    assert timebase.seconds(1) == pytest.approx(1 / 24)
