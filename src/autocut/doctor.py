"""``autocut doctor``: report the environment AutoCut will run in.

Reported facts: AutoCut and Python versions, platform, ffmpeg/ffprobe paths and
versions, and the hardware encoders the ffmpeg binary was built with.
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass

from autocut import __version__
from autocut.media.tools import (
    FFMPEG,
    FFPROBE,
    HARDWARE_ENCODERS,
    available_hardware_encoders,
    find_tool,
    install_hint,
    tool_version,
)


@dataclass(frozen=True)
class ToolInfo:
    """One external tool as found on this machine."""

    name: str
    path: str | None
    version: str | None

    @property
    def found(self) -> bool:
        return self.path is not None

    def render(self) -> str:
        if not self.found:
            return f"{self.name}: NOT FOUND"
        return f"{self.name}: {self.version or 'version unknown'}\n    {self.path}"


@dataclass(frozen=True)
class DoctorReport:
    """Everything ``doctor`` prints."""

    autocut_version: str
    python_version: str
    platform_label: str
    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    encoders: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.ffmpeg.found and self.ffprobe.found


def inspect_tool(name: str) -> ToolInfo:
    path = find_tool(name)
    version = tool_version(path) if path else None
    return ToolInfo(name=name, path=path, version=version)


def build_doctor_report() -> DoctorReport:
    """Probe the environment. Never raises for a missing tool."""
    ffmpeg = inspect_tool(FFMPEG)
    ffprobe = inspect_tool(FFPROBE)
    encoders = available_hardware_encoders(ffmpeg.path) if ffmpeg.found else ()

    problems: list[str] = []
    for tool in (ffmpeg, ffprobe):
        if not tool.found:
            problems.append(f"{tool.name} is not on PATH. {install_hint()}")
    if ffmpeg.found and not encoders:
        problems.append(
            "no hardware H.264/HEVC encoders in this ffmpeg build; "
            "rendering will use libx264 (CPU)"
        )

    return DoctorReport(
        autocut_version=__version__,
        python_version=sys.version.split()[0],
        platform_label=f"{platform.system()} {platform.release()} ({platform.machine()})",
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        encoders=encoders,
        problems=tuple(problems),
    )


def render_doctor(report: DoctorReport) -> str:
    lines = [
        f"AutoCut {report.autocut_version}",
        f"python: {report.python_version}",
        f"platform: {report.platform_label}",
        "",
        report.ffmpeg.render(),
        report.ffprobe.render(),
        "",
        "hardware encoders:",
    ]
    if report.encoders:
        for name in report.encoders:
            lines.append(f"  {name:<22} {HARDWARE_ENCODERS.get(name, '')}".rstrip())
    else:
        lines.append("  none detected (software encoding only)")

    if report.problems:
        lines.append("")
        lines.append("notes:")
        lines.extend(f"  - {problem}" for problem in report.problems)

    status = "ready" if report.ok else "NOT READY"
    lines.append("")
    lines.append(f"status: {status}")
    return "\n".join(lines)
