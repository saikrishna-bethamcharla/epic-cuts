"""Render and timeline export from a Cut List produced by ``autocut run``."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut.cli import app
from autocut.media.probe import probe_media
from tests.media_fixtures import tone_bursts, video_clip, wav_duration

runner = CliRunner()


@pytest.fixture
def assembled(tmp_path: Path) -> Path:
    folder = tmp_path / "clips"
    folder.mkdir()
    for name in ("01.mp4", "02.mp4"):
        wav = tone_bursts(folder / f"{name}.wav", speech=1.0, silence=1.0, repeats=3)
        video_clip(folder / name, audio=wav, seconds=wav_duration(wav))
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            str(folder),
            "-o",
            str(out),
            "--detector",
            "energy",
            "--no-cache",
            "--no-hardware",
        ],
    )
    assert result.exit_code == 0, result.stderr
    return out


def _export(cutlist: Path, fmt: str, target: Path) -> None:
    result = runner.invoke(
        app,
        [
            "export",
            str(cutlist),
            "--format",
            fmt,
            "-o",
            str(target),
            "--no-hardware",
            "--edl-non-drop",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert target.stat().st_size > 0


def test_run_renders_the_assembled_duration(assembled: Path) -> None:
    payload = json.loads((assembled / "cutlist.json").read_text(encoding="utf-8"))
    rendered = assembled / "autocut.mp4"
    info = probe_media(rendered)

    assert info.video is not None
    assert info.video.width == 320
    assert info.audio_streams
    expected = payload["timeline"]["duration"]
    assert abs(info.duration - expected) <= 2 / 30 + 0.01


def test_exported_timelines_match_the_cutlist(assembled: Path, tmp_path: Path) -> None:
    cutlist = assembled / "cutlist.json"
    payload = json.loads(cutlist.read_text(encoding="utf-8"))
    cuts = payload["timeline"]["cuts"]

    edl = tmp_path / "timeline.edl"
    _export(cutlist, "edl", edl)
    events = [
        line
        for line in edl.read_text(encoding="utf-8").splitlines()
        if line[:3].isdigit() and " C " in line
    ]
    assert len(events) == cuts

    xmeml = tmp_path / "timeline.xml"
    _export(cutlist, "xmeml", xmeml)
    xml_root = ET.parse(xmeml).getroot()
    video_items = xml_root.findall("sequence/media/video/track/clipitem")
    assert len(video_items) == cuts
    assert xml_root.findtext("sequence/duration") == str(payload["timeline"]["frames"])

    fcpxml = tmp_path / "timeline.fcpxml"
    _export(cutlist, "fcpxml", fcpxml)
    fcp_root = ET.parse(fcpxml).getroot()
    spine_clips = fcp_root.findall("library/event/project/sequence/spine/asset-clip")
    assert len(spine_clips) == cuts
    assert len(fcp_root.findall("resources/asset")) == 2


def test_render_export_infers_the_format_from_the_extension(
    assembled: Path, tmp_path: Path
) -> None:
    target = tmp_path / "again.mp4"
    result = runner.invoke(
        app,
        [
            "export",
            str(assembled / "cutlist.json"),
            "-o",
            str(target),
            "--no-hardware",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert probe_media(target).duration > 0


def test_export_rejects_a_missing_format_and_output(assembled: Path) -> None:
    result = runner.invoke(app, ["export", str(assembled / "cutlist.json")])
    assert result.exit_code == 2
    assert "pass --format" in result.stderr


def test_export_refuses_a_newer_schema(assembled: Path, tmp_path: Path) -> None:
    payload = json.loads((assembled / "cutlist.json").read_text(encoding="utf-8"))
    payload["schema_version"] = 9
    newer = tmp_path / "newer.json"
    newer.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.invoke(
        app, ["export", str(newer), "--format", "edl", "-o", str(tmp_path / "x.edl")]
    )
    assert result.exit_code == 2
    assert "newer" in result.stderr
