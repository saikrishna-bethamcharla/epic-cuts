"""Filename parsing: 45+ cases covering every pattern the brief lists."""

from __future__ import annotations

import pytest

from autocut.errors import InputError
from autocut.ordering.parser import (
    NumberKind,
    parse_filename,
    strip_media_extension,
    tokenize,
)

B = NumberKind.BARE
L = NumberKind.LETTER
N = NumberKind.NUMERIC

#: (filename, expected raw token, major number, kind, sub text)
PARSE_CASES: list[tuple[str, str, int, NumberKind, str | None]] = [
    ("1.mp4", "1", 1, B, None),
    ("01.mp4", "01", 1, B, None),
    ("10.mp4", "10", 10, B, None),
    ("0.mp4", "0", 0, B, None),
    ("007.mkv", "007", 7, B, None),
    ("0010.mkv", "0010", 10, B, None),
    ("1.MP4", "1", 1, B, None),
    ("clip_2.mp4", "2", 2, B, None),
    ("Take 10.mov", "10", 10, B, None),
    ("02 - intro.mp4", "02", 2, B, None),
    ("Scene3_Shot12.mp4", "3", 3, B, None),
    ("intro_part_2_final.mp4", "2", 2, B, None),
    ("v2_ep01_take3.mp4", "2", 2, B, None),
    ("03_something_v10.mp4", "03", 3, B, None),
    ("clip #4.mp4", "4", 4, B, None),
    ("#1 - intro.mov", "1", 1, B, None),
    ("Take 2 (final).mp4", "2", 2, B, None),
    ("1 (copy).mp4", "1", 1, B, None),
    ("10 - Take 2.mp4", "10", 10, B, None),
    ("1 part 2.mp4", "1", 1, B, None),
    ("shot-12.mp4", "12", 12, B, None),
    ("IMG_20240105_1200.mp4", "20240105", 20240105, B, None),
    ("\u00c9pisode 03 - caf\u00e9.mp4", "03", 3, B, None),
    ("clip1final.mp4", "1", 1, B, None),
    ("1b.mp4", "1b", 1, L, "b"),
    ("1a.mp4", "1a", 1, L, "a"),
    ("1ab.mp4", "1ab", 1, L, "ab"),
    ("Episode 12b.mp4", "12b", 12, L, "b"),
    ("10p.mp4", "10p", 10, L, "p"),
    ("02b_shot.mp4", "02b", 2, L, "b"),
    ("clip_2b_final_v3.mp4", "2b", 2, L, "b"),
    ("clip 1b_02.mp4", "1b", 1, L, "b"),
    ("1.5.mp4", "1.5", 1, N, "5"),
    ("1.50.mp4", "1.50", 1, N, "50"),
    ("1.0.mp4", "1.0", 1, N, "0"),
    ("1.10.mp4", "1.10", 1, N, "10"),
    ("1.5b.mp4", "1.5b", 1, N, "5"),
    ("1-2.mp4", "1-2", 1, N, "2"),
    ("1-2 intro.mp4", "1-2", 1, N, "2"),
    ("2-3-4.mp4", "2-3", 2, N, "3"),
    ("1.2.3.mp4", "1.2", 1, N, "2"),
    ("2024-01-05 - day 1.mp4", "2024-01", 2024, N, "01"),
    # No known media extension: the whole name is parsed, so "1.5" survives.
    ("1", "1", 1, B, None),
    ("1.5", "1.5", 1, N, "5"),
    ("no_ext_1", "1", 1, B, None),
    ("a" * 200 + "_12.mp4", "12", 12, B, None),
]

UNNUMBERED_CASES: list[str] = [
    "no_number.mp4",
    "final.mov",
    "intro.mkv",
    "final cut.webm",
    ".mp4",
]


@pytest.mark.parametrize("filename,raw,major,kind,sub_text", PARSE_CASES)
def test_parse_filename(
    filename: str,
    raw: str,
    major: int,
    kind: NumberKind,
    sub_text: str | None,
) -> None:
    parsed = parse_filename(filename)
    assert parsed is not None, filename
    assert parsed.raw == raw
    assert parsed.major == major
    assert parsed.kind is kind
    assert parsed.sub_text == sub_text


@pytest.mark.parametrize("filename", UNNUMBERED_CASES)
def test_parse_filename_without_number(filename: str) -> None:
    assert parse_filename(filename) is None


def test_fraction_is_normalised() -> None:
    padded = parse_filename("1.50.mp4")
    plain = parse_filename("1.5.mp4")
    assert padded is not None and plain is not None
    assert padded.sub_text != plain.sub_text
    assert padded.sort_key == plain.sort_key


def test_letter_and_numeric_sub_numbers_rank_after_bare() -> None:
    bare = parse_filename("1.mp4")
    letter = parse_filename("1b.mp4")
    numeric = parse_filename("1.5.mp4")
    assert bare is not None and letter is not None and numeric is not None
    assert bare.sort_key < letter.sort_key < numeric.sort_key


def test_strip_media_extension_is_case_insensitive_and_keeps_dotted_names() -> None:
    assert strip_media_extension("clip.MP4") == "clip"
    assert strip_media_extension("1.5") == "1.5"
    assert strip_media_extension("notes.txt") == "notes.txt"
    assert strip_media_extension(".mp4") == ""


def test_tokenize_returns_every_token_left_to_right() -> None:
    tokens = tokenize("S01E02_v3")
    assert [token.raw for token in tokens] == ["01", "02", "3"]


def test_number_rule_last() -> None:
    parsed = parse_filename("S01E02.mp4", rule="last")
    assert parsed is not None
    assert (parsed.raw, parsed.major) == ("02", 2)


def test_number_rule_regex_uses_capture_group() -> None:
    parsed = parse_filename("S01E07.mp4", rule="regex", number_regex=r"E(\d+)")
    assert parsed is not None
    assert (parsed.raw, parsed.major) == ("07", 7)


def test_number_rule_regex_prefers_named_group() -> None:
    parsed = parse_filename(
        "take 12b.mp4", rule="regex", number_regex=r"(?P<number>\d+)b"
    )
    assert parsed is not None
    assert (parsed.raw, parsed.major) == ("12", 12)


def test_number_rule_regex_without_groups_uses_whole_match() -> None:
    parsed = parse_filename("clip7.mp4", rule="regex", number_regex=r"\d+")
    assert parsed is not None
    assert parsed.major == 7


def test_number_rule_regex_without_match_is_unnumbered() -> None:
    assert parse_filename("intro.mp4", rule="regex", number_regex=r"^(\d+)") is None


def test_number_rule_regex_needs_a_pattern() -> None:
    with pytest.raises(InputError, match="needs a --number-regex"):
        parse_filename("1.mp4", rule="regex")


def test_invalid_regex_is_reported_clearly() -> None:
    with pytest.raises(InputError, match=r"invalid --number-regex"):
        parse_filename("1.mp4", rule="regex", number_regex="([0-9")


def test_natural_rule_keeps_every_number_in_the_key() -> None:
    parsed = parse_filename("S01E07.mp4")
    assert parsed is not None
    assert [token.raw for token in parsed.tokens] == ["01", "07"]
    assert parsed.sort_key == ((1, 0, 0.0, ""), (7, 0, 0.0, ""))
    assert parsed.describe() == "1, 7"


def test_first_rule_narrows_the_key_to_one_number() -> None:
    parsed = parse_filename("S01E07.mp4", rule="first")
    assert parsed is not None
    assert parsed.sort_key == ((1, 0, 0.0, ""),)
    assert parsed.describe() == "1"


def test_describe_is_human_readable() -> None:
    assert parse_filename("3.mp4") is not None
    described = parse_filename("3.mp4")
    assert described is not None and described.describe() == "3"
    letter = parse_filename("3b.mp4")
    assert letter is not None and letter.describe() == "3 (letter b)"
