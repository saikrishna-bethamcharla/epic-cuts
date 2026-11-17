"""Doctor report rendering and tool discovery."""

from __future__ import annotations

import pytest

from autocut.doctor import DoctorReport, ToolInfo, build_doctor_report, render_doctor
from autocut.media.tools import available_hardware_encoders, tool_version

MISSING_BINARY = "autocut-definitely-not-installed"


def make_report(
    *,
    ffmpeg: ToolInfo | None = None,
    ffprobe: ToolInfo | None = None,
    encoders: tuple[str, ...] = ("h264_nvenc", "h264_qsv"),
    problems: tuple[str, ...] = (),
) -> DoctorReport:
    return DoctorReport(
        autocut_version="0.1.0",
        python_version="3.12.0",
        platform_label="Test 1.0 (x86_64)",
        ffmpeg=ffmpeg or ToolInfo("ffmpeg", "/usr/bin/ffmpeg", "ffmpeg version 9.0"),
        ffprobe=ffprobe
        or ToolInfo("ffprobe", "/usr/bin/ffprobe", "ffprobe version 9.0"),
        encoders=encoders,
        problems=problems,
    )


def test_render_lists_versions_paths_and_encoders() -> None:
    text = render_doctor(make_report())
    assert "ffmpeg version 9.0" in text
    assert "/usr/bin/ffprobe" in text
    assert "NVENC H.264 (NVIDIA)" in text
    assert "status: ready" in text


def test_render_says_software_only_without_encoders() -> None:
    text = render_doctor(make_report(encoders=()))
    assert "none detected (software encoding only)" in text


def test_missing_tool_makes_the_report_not_ready() -> None:
    report = make_report(ffmpeg=ToolInfo("ffmpeg", None, None))
    text = render_doctor(report)
    assert report.ok is False
    assert "ffmpeg: NOT FOUND" in text
    assert "status: NOT READY" in text


def test_problems_are_listed_as_notes() -> None:
    text = render_doctor(make_report(problems=("slow disk",)))
    assert "notes:" in text
    assert "- slow disk" in text


def test_tool_version_of_missing_binary_is_none() -> None:
    assert tool_version(MISSING_BINARY) is None


def test_available_encoders_of_missing_binary_is_empty() -> None:
    assert available_hardware_encoders(MISSING_BINARY) == ()


def test_build_report_without_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("autocut.doctor.find_tool", lambda _name: None)
    report = build_doctor_report()
    assert report.ok is False
    assert len(report.problems) == 2


@pytest.mark.usefixtures("ffmpeg_available")
def test_build_report_with_ffmpeg(ffmpeg_available: bool) -> None:
    if not ffmpeg_available:
        pytest.skip("ffmpeg not installed")
    report = build_doctor_report()
    assert report.ok is True
    assert report.ffmpeg.version is not None
    assert report.ffmpeg.version.startswith("ffmpeg version")
    assert report.ffprobe.version is not None
