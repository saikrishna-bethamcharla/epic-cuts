"""Frame-based SMPTE timecode for the EDL exporter.

EDLs are single-rate documents, so every timecode is expressed in the
*sequence* rate. Drop-frame labels are used by default at 29.97 and 59.94 fps:
they keep the timecode aligned with wall-clock time, which is what an editor
expects, and the conversion is lossless in both directions.
"""

from __future__ import annotations

from dataclasses import dataclass

from autocut.errors import InputError
from autocut.planning.timebase import Timebase


@dataclass(frozen=True)
class TimecodeFormat:
    """Nominal integer rate plus whether frame numbers skip drop-frame labels."""

    nominal: int
    drop_frame: bool = False

    def __post_init__(self) -> None:
        if self.nominal <= 0:
            raise InputError(f"invalid timecode rate {self.nominal}")
        if self.drop_frame and self.nominal not in (30, 60):
            raise InputError(
                f"drop-frame timecode is only defined for 29.97 and 59.94 fps, "
                f"not {self.nominal} fps"
            )

    @classmethod
    def for_timebase(
        cls, timebase: Timebase, *, drop_frame: bool | None = None
    ) -> TimecodeFormat:
        """The timecode convention for a rational frame rate."""
        nominal = -(-timebase.num // timebase.den)
        ntsc = timebase.den == 1001 and timebase.num in (24000, 30000, 48000, 60000)
        if drop_frame is None:
            drop_frame = ntsc and nominal in (30, 60)
        return cls(nominal=nominal, drop_frame=bool(drop_frame and nominal in (30, 60)))

    def frames(self, seconds: float) -> int:
        """Seconds -> frame number at the nominal rate (half up)."""
        if seconds <= 0:
            return 0
        return int(seconds * self.nominal + 0.5)

    def timecode(self, frame: int) -> str:
        """Frame number -> ``HH:MM:SS:FF``, applying drop-frame labels."""
        if frame < 0:
            raise InputError(f"cannot format a negative frame number ({frame})")
        if self.drop_frame:
            drop = 2 * (self.nominal // 30)
            per_minute = self.nominal * 60 - drop
            per_ten_minutes = self.nominal * 600 - 9 * drop
            ten_minutes, remainder = divmod(frame, per_ten_minutes)
            frame += drop * 9 * ten_minutes
            if remainder > drop:
                frame += drop * ((remainder - drop) // per_minute)
        hours, rest = divmod(frame, self.nominal * 3600)
        minutes, rest = divmod(rest, self.nominal * 60)
        seconds, frames = divmod(rest, self.nominal)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

    def frame_number(self, timecode: str) -> int:
        """``HH:MM:SS:FF`` -> frame number (the inverse of :meth:`timecode`)."""
        text = timecode.strip()
        if text.count(";") == 1:
            text = text.replace(";", ":")
        parts = text.split(":")
        if len(parts) != 4 or not all(part.isdigit() for part in parts):
            raise InputError(f"invalid timecode {timecode!r}; expected HH:MM:SS:FF")
        hours, minutes, seconds, frames = (int(part) for part in parts)
        if minutes > 59 or seconds > 59 or frames >= self.nominal:
            raise InputError(
                f"timecode {timecode!r} is out of range for {self.nominal} fps"
            )
        total_minutes = hours * 60 + minutes
        frame = (total_minutes * 60 + seconds) * self.nominal + frames
        if self.drop_frame:
            drop = 2 * (self.nominal // 30)
            frame -= drop * (total_minutes - total_minutes // 10)
        return frame
