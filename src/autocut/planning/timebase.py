"""Rational timebases and frame-accurate conversion.

Seconds never drive the Cut List: integers do. Every cut point is converted to a
frame index in a rational timebase (``"30000/1001"``, never ``29.97``) and the
seconds in the JSON are *derived* from that frame index, so no float drift can
accumulate across a long assembly.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from autocut.errors import InputError

#: Cap on the denominator used when a float has to be interpreted as a rate.
_MAX_DENOMINATOR = 1_000_001


@dataclass(frozen=True)
class Timebase:
    """A rational frame rate, e.g. ``Timebase(30000, 1001)``."""

    num: int
    den: int = 1

    def __post_init__(self) -> None:
        if self.num <= 0 or self.den <= 0:
            raise InputError(f"invalid timebase {self.num}/{self.den}")

    @classmethod
    def parse(cls, value: str | int | float) -> Timebase:
        """Parse ``"30000/1001"``, ``"25"`` or a numeric rate."""
        if isinstance(value, int):
            return cls(num=value, den=1)
        if isinstance(value, float):
            fraction = Fraction(value).limit_denominator(_MAX_DENOMINATOR)
            return cls(num=fraction.numerator, den=fraction.denominator)
        text = value.strip()
        try:
            fraction = Fraction(text)
        except (ValueError, ZeroDivisionError) as exc:
            raise InputError(f"invalid frame rate {value!r}") from exc
        if fraction <= 0:
            raise InputError(f"invalid frame rate {value!r}")
        return cls(num=fraction.numerator, den=fraction.denominator)

    @property
    def fps(self) -> float:
        return self.num / self.den

    def frames(self, seconds: float) -> int:
        """Seconds -> frame index, rounding half up to the nearest frame."""
        if seconds <= 0:
            return 0
        exact = Fraction(seconds).limit_denominator(_MAX_DENOMINATOR) * self.num
        exact /= self.den
        return int(exact + Fraction(1, 2))

    def seconds(self, frames: int) -> float:
        """Frame index -> seconds, derived (never stored as the source of truth)."""
        return float(Fraction(frames * self.den, self.num))

    def __str__(self) -> str:
        return f"{self.num}/{self.den}"
