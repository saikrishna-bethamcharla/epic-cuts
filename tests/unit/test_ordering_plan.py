"""Ordering plan: the sort contract, gaps, duplicates and unnumbered clips."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.ordering.plan import build_ordering, natural_key
from tests.conftest import make_clips, no_probe


def ordered_names(names: list[str], tmp_path: Path, **kwargs: object) -> list[str]:
    make_clips(tmp_path, names)
    result = build_ordering([tmp_path], prober=no_probe, **kwargs)  # type: ignore[arg-type]
    return [item.filename for item in result.items]


def test_natural_sort_puts_two_before_ten(tmp_path: Path) -> None:
    names = ["10.mp4", "2.mp4", "1.mp4"]
    assert ordered_names(names, tmp_path) == ["1.mp4", "2.mp4", "10.mp4"]


def test_sub_number_contract(tmp_path: Path) -> None:
    names = ["2.mp4", "1-2.mp4", "1.5.mp4", "1b.mp4", "1a.mp4", "1.mp4"]
    assert ordered_names(names, tmp_path) == [
        "1.mp4",
        "1a.mp4",
        "1b.mp4",
        "1.5.mp4",
        "1-2.mp4",
        "2.mp4",
    ]


def test_mixed_patterns_are_ordered_by_first_number(tmp_path: Path) -> None:
    names = ["10.mp4", "02 - intro.mp4", "1b.mov", "1.5.mkv", "3.webm", "1.mp4"]
    assert ordered_names(names, tmp_path) == [
        "1.mp4",
        "1b.mov",
        "1.5.mkv",
        "02 - intro.mp4",
        "3.webm",
        "10.mp4",
    ]


def test_number_rule_last_changes_the_order(tmp_path: Path) -> None:
    names = ["S01E02.mp4", "S01E01.mp4"]
    assert ordered_names(names, tmp_path, number_rule="last") == [
        "S01E01.mp4",
        "S01E02.mp4",
    ]


def test_unnumbered_clips_go_last_in_natural_alphabetical_order(tmp_path: Path) -> None:
    names = ["1.mp4", "b.mp4", "a10.mp4", "a2.mp4"]
    result_names = ordered_names(names, tmp_path)
    assert result_names == ["1.mp4", "a2.mp4", "a10.mp4", "b.mp4"]


def test_unnumbered_policy_error_aborts(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "intro.mp4"])
    with pytest.raises(InputError, match=r"without a clip number: intro\.mp4"):
        build_ordering([tmp_path], prober=no_probe, unnumbered_policy="error")


def test_unknown_unnumbered_policy_is_rejected(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    with pytest.raises(InputError, match="unknown unnumbered policy"):
        build_ordering([tmp_path], prober=no_probe, unnumbered_policy="drop")


def test_gaps_are_reported_for_single_missing_number(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "2.mp4", "4.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert [gap.label for gap in result.problems.gaps] == ["3"]


def test_gaps_are_merged_into_ranges(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "5.mp4", "9.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert [gap.label for gap in result.problems.gaps] == ["2-4", "6-8"]


def test_contiguous_clips_have_no_gaps(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "2.mp4", "3.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert result.problems.gaps == ()
    assert result.problems.summary() == "no problems"


def test_duplicates_are_grouped_by_parsed_number(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "01.mp4", "2.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert len(result.problems.duplicates) == 1
    group = result.problems.duplicates[0]
    assert group.files == ("01.mp4", "1.mp4")
    assert group.number.raw == "01"


def test_sub_numbers_do_not_create_duplicates(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "1a.mp4", "1b.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert result.problems.duplicates == ()


def test_sub_numbers_do_not_fill_a_gap(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "1a.mp4", "3.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert [gap.label for gap in result.problems.gaps] == ["2"]


def test_unreadable_clips_are_reported_and_kept(tmp_path: Path) -> None:
    clips = make_clips(tmp_path, ["1.mp4", "2.mp4"])

    def prober(path: Path) -> tuple[None, str | None]:
        return (None, "ffprobe said no") if path.name == "2.mp4" else (None, None)

    result = build_ordering([tmp_path], prober=prober)
    assert [item.filename for item in result.items] == [clip.name for clip in clips]
    assert result.problems.unreadable == (("2.mp4", "ffprobe said no"),)
    assert [item.status for item in result.items] == ["ok", "unreadable"]
    assert result.usable_items == (result.items[0],)


def test_order_numbers_are_sequential(tmp_path: Path) -> None:
    make_clips(tmp_path, ["5.mp4", "1.mp4", "intro.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert [item.order for item in result.items] == [1, 2, 3]
    assert result.items[-1].warnings == (
        "no clip number in filename; placed at the end",
    )


def test_ignored_files_are_reported(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "notes.txt", "project.xmeml"])
    result = build_ordering([tmp_path], prober=no_probe)
    assert sorted(path.name for path in result.ignored) == [
        "notes.txt",
        "project.xmeml",
    ]


def test_explicit_file_input_is_accepted(tmp_path: Path) -> None:
    target = tmp_path / "7.mp4"
    target.write_bytes(b"")
    result = build_ordering([target], prober=no_probe)
    assert [item.filename for item in result.items] == ["7.mp4"]


def test_settings_are_recorded_in_the_result(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    result = build_ordering(
        [tmp_path], prober=no_probe, number_rule="last", recursive=True
    )
    assert result.settings["number_rule"] == "last"
    assert result.settings["recursive"] is True
    assert result.settings["probed"] is True


def test_probe_can_be_skipped_entirely(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    result = build_ordering([tmp_path], prober=None)
    assert result.settings["probed"] is False
    assert result.items[0].media is None
    assert result.problems.unreadable == ()


def test_natural_key_orders_numbers_numerically() -> None:
    assert sorted(["clip10", "clip2"], key=natural_key) == ["clip2", "clip10"]


def test_empty_folder_reports_no_clips(tmp_path: Path) -> None:
    result = build_ordering([tmp_path], prober=no_probe)
    assert result.items == ()
    assert result.problems.summary() == "no problems"


def test_missing_input_path_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        build_ordering([tmp_path / "nope"], prober=no_probe)
