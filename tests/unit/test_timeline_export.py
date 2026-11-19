"""xmeml and FCPXML structure plus export dispatch."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.exporters import (
    DEFAULT_SUFFIX,
    export_cutlist,
    infer_format,
    normalise_format,
)
from autocut.exporters.fcpxml import build_fcpxml
from autocut.exporters.xmeml import build_xmeml
from autocut.planning.loader import LoadedCutList, load_cutlist
from tests.cutlist_factory import cutlist_payload, write_cutlist


def _loaded(tmp_path: Path) -> LoadedCutList:
    return load_cutlist(write_cutlist(tmp_path))


def test_xmeml_has_sequence_clipitems_and_files(tmp_path: Path) -> None:
    cutlist = _loaded(tmp_path)
    root = ET.fromstring(build_xmeml(cutlist, title="Assembly"))

    sequence = root.find("sequence")
    assert sequence is not None
    assert sequence.findtext("name") == "Assembly"
    assert sequence.findtext("duration") == str(cutlist.total_frames)

    video = sequence.find("media/video")
    assert video is not None
    track = video.find("track")
    assert track is not None
    items = track.findall("clipitem")
    assert len(items) == 3

    first = items[0]
    assert first.findtext("start") == "0"
    assert first.findtext("end") == "50"
    assert first.findtext("in") == "0"
    assert first.findtext("out") == "50"
    file_element = first.find("file")
    assert file_element is not None
    assert file_element.findtext("pathurl", "").startswith("file://localhost/")
    assert file_element.findtext("duration") == "250"

    audio_track = sequence.find("media/audio/track")
    assert audio_track is not None
    assert len(audio_track.findall("clipitem")) == 3


def test_xmeml_marks_ntsc_rates(tmp_path: Path) -> None:
    cutlist = load_cutlist(write_cutlist(tmp_path, cutlist_payload(fps="30000/1001")))
    root = ET.fromstring(build_xmeml(cutlist))
    rate = root.find("sequence/rate")
    assert rate is not None
    assert rate.findtext("timebase") == "30"
    assert rate.findtext("ntsc") == "TRUE"


def test_fcpxml_offsets_accumulate_on_the_spine(tmp_path: Path) -> None:
    cutlist = _loaded(tmp_path)
    root = ET.fromstring(build_fcpxml(cutlist))

    assert root.get("version") == "1.10"
    sequence = root.find("library/event/project/sequence")
    assert sequence is not None
    assert sequence.get("tcFormat") == "NDF"
    assert sequence.get("duration") == "6s"

    spine = sequence.find("spine")
    assert spine is not None
    clips = spine.findall("asset-clip")
    assert len(clips) == 3
    assert [clip.get("offset") for clip in clips] == ["0s", "2s", "4s"]
    assert clips[0].get("start") == "0s"
    assert clips[0].get("duration") == "2s"

    assets = root.findall("resources/asset")
    assert len(assets) == 2
    media_rep = assets[0].find("media-rep")
    assert media_rep is not None
    assert media_rep.get("src", "").startswith("file://")


def test_fcpxml_uses_drop_frame_tc_at_ntsc(tmp_path: Path) -> None:
    cutlist = load_cutlist(write_cutlist(tmp_path, cutlist_payload(fps="30000/1001")))
    root = ET.fromstring(build_fcpxml(cutlist))
    sequence = root.find("library/event/project/sequence")
    assert sequence is not None
    assert sequence.get("tcFormat") == "DF"


def test_format_helpers() -> None:
    assert normalise_format("XMemL") == "xmeml"
    assert infer_format(Path("a.edl")) == "edl"
    assert infer_format(Path("a.fcpxml")) == "fcpxml"
    assert infer_format(Path("a.mov")) == "render"
    with pytest.raises(InputError, match="unknown export format"):
        normalise_format("aaf")
    with pytest.raises(InputError, match="cannot infer"):
        infer_format(Path("a.json"))
    assert set(DEFAULT_SUFFIX) == {"xmeml", "fcpxml", "edl", "render"}


def test_export_writes_each_timeline_format(tmp_path: Path) -> None:
    cutlist = _loaded(tmp_path)
    for fmt in ("xmeml", "fcpxml", "edl"):
        target = tmp_path / f"timeline.{fmt}"
        result = export_cutlist(cutlist, fmt, target)
        assert result.path == target
        assert target.stat().st_size > 0
        if fmt != "edl":
            ET.parse(target)
        else:
            assert "FCM:" in target.read_text(encoding="utf-8")


def test_export_rejects_an_empty_cutlist(tmp_path: Path) -> None:
    payload = cutlist_payload(
        clips=[
            {
                "order": 1,
                "source_path": "a.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "segments": [],
            }
        ]
    )
    loaded = load_cutlist(write_cutlist(tmp_path, payload))
    with pytest.raises(InputError, match="no segments"):
        export_cutlist(loaded, "edl", tmp_path / "out.edl")
