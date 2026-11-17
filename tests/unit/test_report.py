"""Report rendering: duration formatting, the text table and the JSON shape."""

from __future__ import annotations

import json
from pathlib import Path

from autocut.ordering.plan import build_ordering
from autocut.ordering.report import (
    format_duration,
    render_human_report,
    render_json_report,
    write_json_report,
)
from tests.conftest import make_clips, no_probe


def test_format_duration() -> None:
    assert format_duration(None) == "-"
    assert format_duration(0.0) == "00:00.0"
    assert format_duration(62.5) == "01:02.5"
    assert format_duration(3725.0) == "1:02:05.0"
    assert format_duration(-3.0) == "00:00.0"


def test_human_report_has_a_row_per_clip(tmp_path: Path) -> None:
    make_clips(tmp_path, ["10.mp4", "2.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    text = render_human_report(result)
    assert "ordering report" in text
    assert "2.mp4" in text and "10.mp4" in text
    assert text.index("2.mp4") < text.index("10.mp4")
    assert "summary: 2 clip(s)" in text


def test_human_report_reports_every_problem_kind(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "4.mp4", "04.mp4", "outro.mp4"])

    def prober(path: Path) -> tuple[None, str | None]:
        return (None, "probe failed") if path.name == "4.mp4" else (None, None)

    result = build_ordering([tmp_path], prober=prober)
    text = render_human_report(result)
    assert "gap         missing clip number(s) 2-3" in text
    assert "duplicate   04" in text
    assert "no number   outro.mp4" in text
    assert "unreadable  4.mp4" in text
    assert "--strict" in text


def test_human_report_on_empty_folder(tmp_path: Path) -> None:
    result = build_ordering([tmp_path], prober=no_probe)
    assert "no clips found" in render_human_report(result)


def test_long_filenames_are_shortened(tmp_path: Path) -> None:
    name = "x" * 120 + "_1.mp4"
    make_clips(tmp_path, [name])
    text = render_human_report(build_ordering([tmp_path], prober=no_probe))
    assert "..." in text
    assert name not in text


def test_json_report_shape(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "3.mp4"])
    result = build_ordering([tmp_path], prober=no_probe)
    payload = render_json_report(result)
    assert payload["schema_version"] == 1
    assert payload["generated_by"].startswith("autocut ")
    assert [clip["filename"] for clip in payload["clips"]] == ["1.mp4", "3.mp4"]
    assert payload["clips"][0]["number"] == {
        "raw": "1",
        "major": 1,
        "kind": "bare",
        "sub": None,
    }
    assert payload["problems"]["gaps"] == [{"start": 2, "end": 2}]
    assert payload["summary"]["problem_counts"]["gaps"] == 1
    assert json.dumps(payload)  # serialisable


def test_write_json_report_creates_parent_folders(tmp_path: Path) -> None:
    make_clips(tmp_path / "clips", ["1.mp4"])
    result = build_ordering([tmp_path / "clips"], prober=no_probe)
    target = write_json_report(result, tmp_path / "out" / "nested" / "ordering.json")
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8"))["summary"]["clips"] == 1
