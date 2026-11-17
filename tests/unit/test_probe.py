"""ffprobe JSON parsing, without needing ffmpeg installed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from autocut.errors import ProbeError
from autocut.media.probe import MediaInfo, parse_probe_output


def payload(
    *,
    duration: str | None = "3.5",
    video: dict[str, Any] | None = None,
    audio: list[dict[str, Any]] | None = None,
    format_name: str = "mov,mp4,m4a,3gp,3g2,mj2",
    streams: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    built: list[dict[str, Any]] = []
    if streams is not None:
        built.extend(streams)
    else:
        if video is not None:
            built.append({"codec_type": "video", "codec_name": "h264", **video})
        for stream in audio or []:
            built.append({"codec_type": "audio", **stream})
    body: dict[str, Any] = {"streams": built, "format": {"format_name": format_name}}
    if duration is not None:
        body["format"]["duration"] = duration
    return body


VIDEO = {"width": 1920, "height": 1080, "avg_frame_rate": "30000/1001"}


def test_parses_video_and_audio(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.mp4",
        payload(video=VIDEO, audio=[{"index": 1, "codec_name": "aac", "channels": 2}]),
    )
    assert info.duration == 3.5
    assert info.video is not None
    assert info.video.fps == "30000/1001"
    assert info.resolution == "1920x1080"
    assert info.is_supported is True
    assert info.first_audio is not None
    assert info.first_audio.channels == 2


def test_attached_picture_is_not_the_video_stream(tmp_path: Path) -> None:
    cover = {
        "codec_type": "video",
        "codec_name": "mjpeg",
        "width": 600,
        "height": 600,
        "disposition": {"attached_pic": 1},
    }
    info = parse_probe_output(
        tmp_path / "1.mp4",
        payload(
            streams=[cover, {"codec_type": "video", "codec_name": "h264", **VIDEO}]
        ),
    )
    assert info.video is not None
    assert info.video.codec == "h264"


def test_audio_only_file_is_not_supported(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.m4a", payload(audio=[{"index": 0, "codec_name": "aac"}])
    )
    assert info.video is None
    assert info.is_supported is False


def test_unsupported_container_is_flagged(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.ogg", payload(video=VIDEO, format_name="ogg")
    )
    assert info.is_supported_container is False
    assert info.is_supported is False


def test_duration_falls_back_to_stream_duration(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.mkv",
        payload(
            duration=None,
            streams=[{"codec_type": "video", "duration": "7.25", **VIDEO}],
        ),
    )
    assert info.duration == 7.25


def test_unknown_duration_is_a_probe_error(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="duration is unknown"):
        parse_probe_output(tmp_path / "1.mp4", payload(duration="N/A", video=VIDEO))


def test_missing_stream_list_is_a_probe_error(tmp_path: Path) -> None:
    with pytest.raises(ProbeError, match="no stream information"):
        parse_probe_output(tmp_path / "1.mp4", {"format": {"duration": "1.0"}})


def test_fps_falls_back_to_r_frame_rate(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.mp4",
        payload(
            video={
                "width": 640,
                "height": 360,
                "avg_frame_rate": "0/0",
                "r_frame_rate": "25/1",
            }
        ),
    )
    assert info.video is not None
    assert info.video.fps == "25/1"


def test_avg_and_r_frame_rate_unusable_gives_none(tmp_path: Path) -> None:
    info = parse_probe_output(
        tmp_path / "1.mp4",
        payload(
            video={
                "width": 640,
                "height": 360,
                "avg_frame_rate": "0/0",
                "r_frame_rate": "0",
            }
        ),
    )
    assert info.video is not None
    assert info.video.fps is None


def test_missing_video_dimensions_give_no_resolution(tmp_path: Path) -> None:
    info = parse_probe_output(tmp_path / "1.mp4", payload(video={}))
    assert info.resolution is None


def test_container_tokens_are_split(tmp_path: Path) -> None:
    info: MediaInfo = parse_probe_output(
        tmp_path / "1.mp4", payload(video=VIDEO, format_name="matroska,webm")
    )
    assert info.container_tokens == frozenset({"matroska", "webm"})
    assert info.is_supported_container is True
