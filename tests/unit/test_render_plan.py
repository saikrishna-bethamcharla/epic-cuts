"""Render planning: filter graph, encoder choice and FFmpeg arguments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autocut.errors import InputError
from autocut.planning.loader import LoadedCutList, load_cutlist
from autocut.render.ffmpeg import (
    RenderSettings,
    build_plan,
    build_render_command,
    encoder_candidates,
    suggested_output,
)
from tests.cutlist_factory import cutlist_payload, write_cutlist


def _loaded(tmp_path: Path, payload: dict[str, Any] | None = None) -> LoadedCutList:
    return load_cutlist(write_cutlist(tmp_path, payload))


def test_plan_trims_source_frames_and_joins(tmp_path: Path) -> None:
    plan = build_plan(_loaded(tmp_path), crossfade_ms=10)

    assert len(plan.inputs) == 2
    assert plan.total_frames == 150
    assert plan.has_audio is True
    graph = plan.filter_graph
    assert "trim=start_frame=0:end_frame=50" in graph
    assert "trim=start_frame=75:end_frame=125" in graph
    assert "fps=25/1" in graph
    assert "scale=1920:1080" in graph
    assert "concat=n=3:v=1:a=1[vout][aout]" in graph
    assert graph.count("afade=t=in") == 3


def test_clips_without_audio_get_silence(tmp_path: Path) -> None:
    payload = cutlist_payload(
        clips=[
            {
                "order": 1,
                "source_path": "a.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "audio_stream": 1,
                "segments": [(0, 50)],
            },
            {
                "order": 2,
                "source_path": "b.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "audio_stream": None,
                "segments": [(0, 50)],
            },
        ]
    )
    plan = build_plan(_loaded(tmp_path, payload), audio_ordinals={1: 0, 2: None})
    assert plan.has_audio is True
    assert "anullsrc=channel_layout=stereo" in plan.filter_graph


def test_video_only_cutlist_drops_the_audio_graph(tmp_path: Path) -> None:
    payload = cutlist_payload(
        clips=[
            {
                "order": 1,
                "source_path": "a.mp4",
                "duration_frames": 100,
                "fps": "25/1",
                "audio_stream": None,
                "segments": [(0, 50), (70, 100)],
            }
        ]
    )
    plan = build_plan(_loaded(tmp_path, payload), audio_ordinals={1: None})
    assert plan.has_audio is False
    assert "a=0[vout]" in plan.filter_graph
    assert "anullsrc" not in plan.filter_graph


def test_zero_crossfade_removes_fades(tmp_path: Path) -> None:
    plan = build_plan(_loaded(tmp_path), crossfade_ms=0)
    assert "afade" not in plan.filter_graph


def test_empty_cutlist_cannot_be_planned(tmp_path: Path) -> None:
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
    with pytest.raises(InputError, match="no segments"):
        build_plan(_loaded(tmp_path, payload))


def test_encoder_candidates_prefer_hardware_then_software() -> None:
    settings = RenderSettings()
    assert encoder_candidates(settings, ["h264_nvenc", "hevc_nvenc"]) == (
        "h264_nvenc",
        "libx264",
    )
    assert encoder_candidates(RenderSettings(hardware=False), ["h264_nvenc"]) == (
        "libx264",
    )
    assert encoder_candidates(RenderSettings(encoder="h264_qsv"), []) == (
        "h264_qsv",
        "libx264",
    )
    assert encoder_candidates(RenderSettings(codec="libx265"), ["hevc_qsv"]) == (
        "hevc_qsv",
        "libx265",
    )
    assert encoder_candidates(RenderSettings(codec="prores_ks"), ["h264_nvenc"]) == (
        "prores_ks",
    )


def test_render_command_maps_outputs_and_quality(tmp_path: Path) -> None:
    plan = build_plan(_loaded(tmp_path))
    command = build_render_command(
        plan, tmp_path / "out.mp4", RenderSettings(crf=16, preset="slow"), "libx264"
    )
    text = " ".join(command)
    assert "-map [vout]" in text
    assert "-map [aout]" in text
    assert "-crf 16" in text
    assert "-preset slow" in text
    assert "-movflags +faststart" in text
    assert command[-1].endswith("out.mp4")
    assert command.count("-i") == 2


def test_nvenc_uses_constant_quality_flags(tmp_path: Path) -> None:
    plan = build_plan(_loaded(tmp_path))
    command = build_render_command(
        plan, tmp_path / "out.mp4", RenderSettings(crf=20), "h264_nvenc"
    )
    assert "-cq" in command
    assert "-crf" not in command


def test_render_settings_are_validated() -> None:
    with pytest.raises(InputError, match="crf"):
        RenderSettings(crf=99)
    with pytest.raises(InputError, match="crossfade"):
        RenderSettings(crossfade_ms=-1)
    assert suggested_output(Path("out/cutlist.json")) == Path("out/cutlist.mp4")
