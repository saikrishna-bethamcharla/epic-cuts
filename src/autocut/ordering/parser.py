"""Extract the clip number from a filename.

Ordering contract (brief 3.1), lower sorts first::

    1  <  1a  <  1b  <  1.5  <  1-2  <  2

A filename is reduced to its name without a *known media extension* (so ``1.5``
stays ``1.5`` instead of collapsing to ``1``), then scanned for number tokens::

    major          digits                       "1", "01", "10"
    [".frac"]      decimal continuation         "1.5"
    [alpha]        1-2 letters, lower-cased     "1a", "1b"    ["-"sub]       dash continuation            "1-2"

The sort key is ``(major, kind, sub_value, sub_text)`` where ``kind`` puts bare
numbers before letter suffixes before numeric sub-numbers. Fractions are
normalised (``1.50`` == ``1.5``) and compared as their fractional value, so
``1.5`` (0.5) sorts before ``1-2`` (2). ``docs/DECISIONS.md`` records why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal

from autocut.errors import InputError

#: Extensions that are stripped before parsing. Probing decides support; this
#: set only stops a dotted name from being mistaken for a sub-number.
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".webm", ".mxf", ".m4v"}
)

NumberRule = Literal["first", "last", "regex"]

TokenKey = tuple[int, int, float, str]

_TOKEN_RE = re.compile(
    r"(?P<major>\d+)"
    r"(?:\.(?P<frac>\d+))?"
    r"(?:(?P<alpha>[A-Za-z]{1,2})(?![A-Za-z0-9]))?"
    r"(?:-(?P<range>\d+))?"
)


class NumberKind(IntEnum):
    """How a clip number is qualified; the value is also its sort rank."""

    BARE = 0
    LETTER = 1
    NUMERIC = 2

    @property
    def label(self) -> str:
        return {
            NumberKind.BARE: "bare",
            NumberKind.LETTER: "letter",
            NumberKind.NUMERIC: "numeric",
        }[self]


@dataclass(frozen=True)
class ParsedNumber:
    """A clip number as written in a filename, plus its sort identity."""

    raw: str
    major: int
    kind: NumberKind = NumberKind.BARE
    sub_text: str | None = None
    sub_value: float | None = None

    @property
    def sort_key(self) -> TokenKey:
        """Total order for clip numbers; equal keys mean a duplicate."""
        if self.kind is NumberKind.BARE:
            text = ""
        elif self.kind is NumberKind.LETTER:
            text = self.sub_text or ""
        else:
            text = f"{self.sub_value or 0.0:g}"
        return (self.major, int(self.kind), self.sub_value or 0.0, text)

    def describe(self) -> str:
        """Human form used in reports, e.g. ``"3 (letter b)"``."""
        if self.kind is NumberKind.BARE:
            return f"{self.major}"
        return f"{self.major} ({self.kind.label} {self.sub_text})"


def strip_media_extension(filename: str) -> str:
    """Drop a trailing known media extension, case-insensitively."""
    lowered = filename.lower()
    for extension in MEDIA_EXTENSIONS:
        if lowered.endswith(extension) and len(filename) >= len(extension):
            return filename[: -len(extension)]
    return filename


def _subgroup_value(text: str, *, fractional: bool) -> float:
    if fractional:
        return float(f"0.{text}")
    return float(text)


def _from_match(match: re.Match[str]) -> ParsedNumber:
    major = int(match.group("major"))
    fraction = match.group("frac")
    alpha = match.group("alpha")
    ran = match.group("range")

    if fraction is not None:
        return ParsedNumber(
            raw=match.group(0),
            major=major,
            kind=NumberKind.NUMERIC,
            sub_text=fraction,
            sub_value=_subgroup_value(fraction, fractional=True),
        )
    if ran is not None:
        return ParsedNumber(
            raw=match.group(0),
            major=major,
            kind=NumberKind.NUMERIC,
            sub_text=ran,
            sub_value=_subgroup_value(ran, fractional=False),
        )
    if alpha:
        return ParsedNumber(
            raw=match.group(0),
            major=major,
            kind=NumberKind.LETTER,
            sub_text=alpha.lower(),
        )
    return ParsedNumber(raw=match.group(0), major=major)


def tokenize(name: str) -> list[ParsedNumber]:
    """Every clip-number token found in ``name``, left to right."""
    return [_from_match(match) for match in _TOKEN_RE.finditer(name)]


def validate_number_regex(pattern: str | None) -> None:
    """Fail fast with a readable message when a user regex is unusable."""
    if not pattern:
        raise InputError("number_rule 'regex' needs a --number-regex pattern")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise InputError(f"invalid --number-regex {pattern!r}: {exc}") from exc


def _captured(match: re.Match[str]) -> str | None:
    if "number" in match.re.groupindex:
        value = match.group("number")
    elif match.re.groups >= 1:
        value = match.group(1)
    else:
        value = match.group(0)
    return value if isinstance(value, str) and value else None


def parse_filename(
    filename: str,
    *,
    rule: NumberRule = "first",
    number_regex: str | None = None,
) -> ParsedNumber | None:
    """Return the clip number for ``filename``, or None when it has none.

    ``rule`` selects the first number token, the last one, or the text captured
    by ``number_regex`` (group ``number`` when present, else group 1).
    """
    stem = strip_media_extension(filename)

    if rule == "regex":
        validate_number_regex(number_regex)
        assert number_regex is not None  # narrow for type checkers
        match = re.search(number_regex, stem)
        if match is None:
            return None
        captured = _captured(match)
        if captured is None:
            return None
        tokens = tokenize(captured)
        return tokens[0] if tokens else None

    tokens = tokenize(stem)
    if not tokens:
        return None
    return tokens[-1] if rule == "last" else tokens[0]
