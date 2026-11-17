"""Property tests for the sort order and duplicate reporting (brief section 8)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from autocut.ordering.parser import NumberKey
from autocut.ordering.plan import build_ordering
from tests.conftest import no_probe

SUFFIXES = ["", "a", "b", "ab"]
SUB_NUMBERS = ["", ".5", ".50", "-2"]


@st.composite
def clip_names(draw: st.DrawFn) -> list[str]:
    """Unique filenames: the positional suffix keeps names distinct."""
    count = draw(st.integers(min_value=1, max_value=6))
    names: list[str] = []
    for index in range(count):
        number = draw(st.integers(min_value=0, max_value=20))
        suffix = draw(st.sampled_from(SUFFIXES))
        sub = draw(st.sampled_from(SUB_NUMBERS))
        names.append(f"clip{number}{suffix}{sub}_{index}.mp4")
    return names


def build_result(names: list[str]) -> tuple[list[str], list[NumberKey]]:
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        for name in names:
            (directory / name).write_bytes(b"")
        result = build_ordering([directory], prober=no_probe)
    ordered = [item.filename for item in result.items]
    keys = [item.number.sort_key for item in result.items if item.number is not None]
    return ordered, keys


@settings(max_examples=60, deadline=None)
@given(names=clip_names())
def test_ordering_is_a_deterministic_permutation(names: list[str]) -> None:
    ordered, keys = build_result(names)
    assert sorted(ordered) == sorted(names)
    assert keys == sorted(keys)
    assert build_result(names)[0] == ordered


def test_order_numbers_are_sequential_for_generated_names() -> None:
    names = ["6.mp4", "1b.mp4", "intro.mp4"]
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        for name in names:
            (directory / name).write_bytes(b"")
        result = build_ordering([directory], prober=no_probe)
    assert [item.order for item in result.items] == [1, 2, 3]


@st.composite
def number_parts(draw: st.DrawFn) -> list[tuple[int, str, str]]:
    count = draw(st.integers(min_value=1, max_value=6))
    return [
        (
            draw(st.integers(min_value=0, max_value=10)),
            draw(st.sampled_from(SUFFIXES)),
            draw(st.sampled_from(SUB_NUMBERS)),
        )
        for _ in range(count)
    ]


@settings(max_examples=50, deadline=None)
@given(parts=number_parts())
def test_duplicate_groups_match_equal_sort_keys(
    parts: list[tuple[int, str, str]],
) -> None:
    names = [
        f"clip{number}{suffix}{sub}_{index}.mp4"
        for index, (number, suffix, sub) in enumerate(parts)
    ]
    with tempfile.TemporaryDirectory() as raw:
        directory = Path(raw)
        for name in names:
            (directory / name).write_bytes(b"")
        result = build_ordering([directory], prober=no_probe)

    _, keys = build_result(names)
    expected_extra = len(keys) - len(set(keys))
    reported = sum(len(group.files) - 1 for group in result.problems.duplicates)
    assert reported == expected_extra
