"""Build the ordering plan: parse, sort, probe and collect problems.

The result is the machine-readable ordering report; the canonical Cut List
(M3) is built from it. Nothing here mutates or copies source media.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from natsort import natsort_keygen

from autocut.errors import InputError
from autocut.media.probe import MediaInfo, probe_safe
from autocut.ordering.discovery import discover
from autocut.ordering.parser import (
    NumberRule,
    ParsedNumber,
    TokenKey,
    parse_filename,
    validate_number_regex,
)

LOGGER = logging.getLogger(__name__)

#: ``(media info, issue)``; the issue is None for a usable clip.
Prober = Callable[[Path], "tuple[MediaInfo | None, str | None]"]

_NATURAL = natsort_keygen()


def natural_key(text: str) -> Any:
    """Natural sort key, so ``2`` sorts before ``10``."""
    return _NATURAL(text)


@dataclass(frozen=True)
class OrderedItem:
    """One clip in its final position."""

    order: int
    path: Path
    number: ParsedNumber | None
    media: MediaInfo | None = None
    issue: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def numbered(self) -> bool:
        return self.number is not None

    @property
    def usable(self) -> bool:
        return self.issue is None

    @property
    def duration(self) -> float | None:
        return self.media.duration if self.media is not None else None

    @property
    def status(self) -> str:
        if self.issue is not None:
            return "unreadable"
        if self.number is None:
            return "no-number"
        return "ok"

    def to_json(self) -> dict[str, Any]:
        return {
            "order": self.order,
            "source_path": str(self.path),
            "filename": self.filename,
            "number": (
                None
                if self.number is None
                else {
                    "raw": self.number.raw,
                    "major": self.number.major,
                    "kind": self.number.kind.label,
                    "sub": self.number.sub_text,
                }
            ),
            "duration": self.duration,
            "fps": self.media.video.fps if self.media and self.media.video else None,
            "resolution": self.media.resolution if self.media else None,
            "container": self.media.container if self.media else None,
            "audio_streams": len(self.media.audio_streams) if self.media else None,
            "status": self.status,
            "issue": self.issue,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class Gap:
    """A run of missing sequence numbers, both ends inclusive."""

    start: int
    end: int

    @property
    def label(self) -> str:
        return str(self.start) if self.start == self.end else f"{self.start}-{self.end}"

    def to_json(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass(frozen=True)
class DuplicateGroup:
    """Two or more files that claim the same clip number."""

    number: ParsedNumber
    files: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {"number": self.number.raw, "files": list(self.files)}


@dataclass(frozen=True)
class OrderingProblems:
    """Everything the user must be told before a single frame is cut."""

    gaps: tuple[Gap, ...] = ()
    duplicates: tuple[DuplicateGroup, ...] = ()
    unnumbered: tuple[str, ...] = ()
    unreadable: tuple[tuple[str, str], ...] = ()

    @property
    def counts(self) -> dict[str, int]:
        return {
            "gaps": len(self.gaps),
            "duplicates": len(self.duplicates),
            "unnumbered": len(self.unnumbered),
            "unreadable": len(self.unreadable),
        }

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def has_problems(self) -> bool:
        return self.total > 0

    def summary(self) -> str:
        if not self.has_problems:
            return "no problems"
        parts = [
            f"{count} {name[:-1] if count == 1 and name.endswith('s') else name}"
            for name, count in self.counts.items()
            if count
        ]
        return ", ".join(parts)

    def to_json(self) -> dict[str, Any]:
        return {
            "gaps": [gap.to_json() for gap in self.gaps],
            "duplicates": [group.to_json() for group in self.duplicates],
            "unnumbered": list(self.unnumbered),
            "unreadable": [
                {"file": name, "reason": reason} for name, reason in self.unreadable
            ],
        }


@dataclass(frozen=True)
class OrderingResult:
    """The ordering stage's full output, shared by the CLI and later the service."""

    inputs: tuple[Path, ...]
    settings: dict[str, Any]
    items: tuple[OrderedItem, ...]
    problems: OrderingProblems = field(default_factory=OrderingProblems)
    ignored: tuple[Path, ...] = ()

    @property
    def total_duration(self) -> float:
        return sum(item.duration or 0.0 for item in self.items)

    @property
    def usable_items(self) -> tuple[OrderedItem, ...]:
        return tuple(item for item in self.items if item.usable)


def _find_gaps(majors: set[int]) -> tuple[Gap, ...]:
    if len(majors) < 2:
        return ()
    gaps: list[Gap] = []
    start: int | None = None
    for expected in range(min(majors), max(majors) + 1):
        if expected in majors:
            if start is not None:
                gaps.append(Gap(start=start, end=expected - 1))
                start = None
        elif start is None:
            start = expected
    if start is not None:  # pragma: no cover - range always ends on a present major
        gaps.append(Gap(start=start, end=max(majors)))
    return tuple(gaps)


def _duplicates(
    numbered: Sequence[tuple[ParsedNumber, Path]],
) -> tuple[DuplicateGroup, ...]:
    grouped: dict[tuple[TokenKey, ...], list[tuple[ParsedNumber, Path]]] = {}
    for number, path in numbered:
        grouped.setdefault(number.sort_key, []).append((number, path))
    duplicates = [
        DuplicateGroup(
            number=entries[0][0],
            files=tuple(path.name for _, path in entries),
        )
        for _, entries in sorted(grouped.items())
        if len(entries) > 1
    ]
    return tuple(duplicates)


def build_ordering(
    inputs: Sequence[Path | str],
    *,
    number_rule: NumberRule = "natural",
    number_regex: str | None = None,
    recursive: bool = False,
    unnumbered_policy: str = "end",
    prober: Prober | None = probe_safe,
) -> OrderingResult:
    """Order clips by the number in their filename and report every problem.

    ``prober`` may be None to skip ffprobe (ordering only, no media facts).
    """
    if unnumbered_policy not in {"end", "error"}:
        raise InputError(
            f"unknown unnumbered policy {unnumbered_policy!r}; use 'end' or 'error'"
        )
    if number_rule == "regex":
        validate_number_regex(number_regex)

    input_paths = tuple(Path(raw).expanduser() for raw in inputs)
    found = discover(input_paths, recursive=recursive)

    numbered: list[tuple[ParsedNumber, Path]] = []
    unnumbered: list[Path] = []
    for path in found.files:
        number = parse_filename(path.name, rule=number_rule, number_regex=number_regex)
        if number is None:
            unnumbered.append(path)
        else:
            numbered.append((number, path))

    if unnumbered and unnumbered_policy == "error":
        names = ", ".join(path.name for path in unnumbered)
        raise InputError(f"files without a clip number: {names}")

    numbered.sort(key=lambda entry: (entry[0].sort_key, natural_key(entry[1].name)))
    unnumbered.sort(key=lambda path: natural_key(path.name))

    entries: list[tuple[ParsedNumber | None, Path]] = [
        *((number, path) for number, path in numbered),
        *((None, path) for path in unnumbered),
    ]

    items: list[OrderedItem] = []
    unreadable: list[tuple[str, str]] = []
    for order, (number, path) in enumerate(entries, start=1):
        media: MediaInfo | None = None
        issue: str | None = None
        if prober is not None:
            media, issue = prober(path)
            if issue is not None:
                unreadable.append((path.name, issue))
                LOGGER.warning("clip %d unreadable: %s (%s)", order, path.name, issue)
        warnings: list[str] = []
        if number is None:
            warnings.append("no clip number in filename; placed at the end")
        items.append(
            OrderedItem(
                order=order,
                path=path,
                number=number,
                media=media,
                issue=issue,
                warnings=tuple(warnings),
            )
        )

    problems = OrderingProblems(
        gaps=_find_gaps({number.major for number, _ in numbered}),
        duplicates=_duplicates(numbered),
        unnumbered=tuple(path.name for path in unnumbered),
        unreadable=tuple(unreadable),
    )

    return OrderingResult(
        inputs=input_paths,
        settings={
            "number_rule": number_rule,
            "number_regex": number_regex,
            "recursive": recursive,
            "unnumbered_policy": unnumbered_policy,
            "probed": prober is not None,
        },
        items=tuple(items),
        problems=problems,
        ignored=found.ignored,
    )
