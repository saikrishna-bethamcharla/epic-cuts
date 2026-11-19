"""Cut List loading: paths, invariants and clear rejections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.planning.loader import CutListSummary, load_cutlist, parse_cutlist
from tests.cutlist_factory import cutlist_payload, write_cutlist


def test_load_resolves_relative_sources_and_frames(tmp_path: Path) -> None:
    path = write_cutlist(tmp_path)
    cutlist = load_cutlist(path)

    assert cutlist.schema_version == 1
    assert str(cutlist.timebase) == "25/1"
    assert cutlist.clips[0].source_path == (tmp_path / "footage" / "01.mp4").resolve()
    assert cutlist.total_frames == 150
    assert cutlist.duration_seconds == pytest.approx(6.0)
    assert [clip.kept_frames for clip in cutlist.clips] == [100, 50]
    summary = CutListSummary.of(cutlist)
    assert summary.clips == 2
    assert summary.cuts == 3
    assert summary.frames == 150


def test_missing_sources_are_reported(tmp_path: Path) -> None:
    cutlist = load_cutlist(write_cutlist(tmp_path))
    assert len(cutlist.missing_sources()) == 2


def test_newer_schema_is_rejected(tmp_path: Path) -> None:
    payload = cutlist_payload()
    payload["schema_version"] = 2
    with pytest.raises(InputError, match="newer"):
        parse_cutlist(payload, tmp_path / "cutlist.json")


def test_non_contiguous_timeline_is_rejected(tmp_path: Path) -> None:
    payload = cutlist_payload()
    payload["clips"][1]["segments"][0]["rec_in_frame"] += 5
    payload["clips"][1]["segments"][0]["rec_out_frame"] += 5
    with pytest.raises(InputError, match="contiguous"):
        parse_cutlist(payload, tmp_path / "cutlist.json")


def test_segment_outside_source_is_rejected(tmp_path: Path) -> None:
    payload = cutlist_payload()
    payload["clips"][0]["segments"][0]["src_out_frame"] = 9999
    with pytest.raises(InputError, match="outside the source"):
        parse_cutlist(payload, tmp_path / "cutlist.json")


def test_invalid_json_and_missing_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(InputError, match="not valid JSON"):
        load_cutlist(broken)
    with pytest.raises(InputError, match="does not exist"):
        load_cutlist(tmp_path / "nope.json")


def test_duration_frames_must_be_positive(tmp_path: Path) -> None:
    payload = cutlist_payload()
    payload["clips"][0]["duration_frames"] = 0
    with pytest.raises(InputError, match="positive"):
        parse_cutlist(payload, tmp_path / "cutlist.json")


def test_unknown_keys_are_ignored(tmp_path: Path) -> None:
    payload = cutlist_payload()
    payload["future"] = {"anything": True}
    payload["sequence"]["future_field"] = 1
    loaded = parse_cutlist(payload, tmp_path / "cutlist.json")
    assert loaded.title == "cutlist"


def test_json_roundtrip_matches_written_file(tmp_path: Path) -> None:
    path = write_cutlist(tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert len(payload["clips"]) == 2
    loaded = load_cutlist(path)
    assert loaded.clips[1].segments[0].src_in_frame == 10
