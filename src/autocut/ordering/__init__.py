"""Ordering layer: filename numbers, discovery and the sort order."""

from __future__ import annotations

from autocut.ordering.discovery import Discovery, discover
from autocut.ordering.parser import NumberKind, ParsedNumber, parse_filename
from autocut.ordering.plan import (
    DuplicateGroup,
    Gap,
    OrderedItem,
    OrderingProblems,
    OrderingResult,
    build_ordering,
)

__all__ = [
    "Discovery",
    "DuplicateGroup",
    "Gap",
    "NumberKind",
    "OrderedItem",
    "OrderingProblems",
    "OrderingResult",
    "ParsedNumber",
    "build_ordering",
    "discover",
    "parse_filename",
]
