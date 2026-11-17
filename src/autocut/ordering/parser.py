"""Extract clip numbers from a filename and define their sort order.

The default rule is ``natural``: *every* number token in the name is compared,
left to right, so ``S01E01`` sorts before ``S01E02`` and ``Scene2_Shot1`` before
``Scene2_Shot3``. ``first``, ``last`` and ``regex`` are explicit overrides that
narrow the key to one chosen number.

A filename is reduced to its name without a *known media extension* (so ``1.5``
stays ``1.5`` instead of collapsing to ``1``), then scanned for number tokens::

    major          digits                       "1", "01", "10"
    [".frac"]      decimal continuation         "1.5"
    [alpha]        1-2 letters, lower-cased     "1a", "1b"
    ["-"sub]       dash continuation            "1-2"

A token's key is ``(major, kind, sub_value, sub_text)``: bare numbers rank
before letter suffixes before numeric sub-numbers, fractions are normalised
(``1.50`` == ``1.5``) and compared by value, so ``1.5`` (0.5) sorts before
``1-2`` (2). A filename's key is the tuple of its token keys, which makes
``1 < 1a < 1b < 1.5 < 1-2 < 2`` fall out of ordinary tuple comparison.
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

NumberRule = Literal["natural", "first", "last", "regex"]

TokenKey = tuple[int, int, float, str]
NumberKey = tuple[TokenKey, ...]

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
class NumberToken:
    """One number as written in a filename."""

    raw: str
    major: int
    kind: NumberKind = NumberKind.BARE
    sub_text: str | None = None
    sub_value: float | None = None

    @property
    def sort_key(self) -> TokenKey:
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


@dataclass(frozen=True)
class ParsedNumber:
    """Every clip number in a filename, plus the ordering key they produce."""

    tokens: tuple[NumberToken, ...]
    rule: NumberRule = "natural"

    @property
    def chosen(self) -> NumberToken:
        """The number shown in reports and used for gap detection."""
        return self.tokens[-1] if self.rule == "last" else self.tokens[0]

    @property
    def raw(self) -> str:
        return self.chosen.raw

    @property
    def major(self) -> int:
        return self.chosen.major

    @property
    def kind(self) -> NumberKind:
        return self.chosen.kind

    @property
    def sub_text(self) -> str | None:
        return self.chosen.sub_text

    @property
    def sub_value(self) -> float | None:
        return self.chosen.sub_value

    @property
    def sort_key(self) -> NumberKey:
        """Total order for clip numbers; equal keys mean a duplicate.

        ``natural`` keeps every token, so only filenames whose full number
        sequence matches are duplicates. The other rules use the chosen token.
        """
        if self.rule == "natural":
            return tuple(token.sort_key for token in self.tokens)
        return (self.chosen.sort_key,)

    def describe(self) -> str:
        if self.rule == "natural" and len(self.tokens) > 1:
            shown = ", ".join(token.describe() for token in self.tokens[:3])
            return shown if len(self.tokens) <= 3 else f"{shown}, ..."
        return self.chosen.describe()


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


def _from_match(match: re.Match[str]) -> NumberToken:
    major = int(match.group("major"))
    fraction = match.group("frac")
    alpha = match.group("alpha")
    ran = match.group("range")

    if fraction is not None:
        return NumberToken(
            raw=match.group(0),
            major=major,
            kind=NumberKind.NUMERIC,
            sub_text=fraction,
            sub_value=_subgroup_value(fraction, fractional=True),
        )
    if ran is not None:
        return NumberToken(
            raw=match.group(0),
            major=major,
            kind=NumberKind.NUMERIC,
            sub_text=ran,
            sub_value=_subgroup_value(ran, fractional=False),
        )
    if alpha:
        return NumberToken(
            raw=match.group(0),
            major=major,
            kind=NumberKind.LETTER,
            sub_text=alpha.lower(),
        )
    return NumberToken(raw=match.group(0), major=major)


def tokenize(name: str) -> list[NumberToken]:
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
    rule: NumberRule = "natural",
    number_regex: str | None = None,
) -> ParsedNumber | None:
    """Return the clip number for ``filename``, or None when it has none.

    ``natural`` compares every number in the name (the default), ``first`` and
    ``last`` pick one, and ``regex`` uses the text captured by ``number_regex``
    (group ``number`` when present, else group 1).
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
        if not tokens:
            return None
        return ParsedNumber(tokens=(tokens[0],), rule="regex")

    tokens = tokenize(stem)
    if not tokens:
        return None
    return ParsedNumber(tokens=tuple(tokens), rule=rule)
