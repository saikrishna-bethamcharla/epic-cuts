"""Locating and interrogating the FFmpeg binaries.

Every subprocess call passes an argument list (never a shell string) and uses
``-hide_banner`` so version and encoder parsing stays predictable.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Sequence

from autocut.errors import ProcessingError, ToolMissingError

LOGGER = logging.getLogger(__name__)

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

INSTALL_HINTS: dict[str, str] = {
    "Windows": "winget install Gyan.FFmpeg  (or place ffmpeg.exe on PATH)",
    "Darwin": "brew install ffmpeg",
    "Linux": "sudo apt install ffmpeg  (or your distribution's package)",
}

#: Hardware encoders AutoCut can use, with the label shown by ``autocut doctor``.
HARDWARE_ENCODERS: dict[str, str] = {
    "h264_nvenc": "NVENC H.264 (NVIDIA)",
    "hevc_nvenc": "NVENC HEVC (NVIDIA)",
    "av1_nvenc": "NVENC AV1 (NVIDIA)",
    "h264_qsv": "Quick Sync H.264 (Intel)",
    "hevc_qsv": "Quick Sync HEVC (Intel)",
    "h264_amf": "AMF H.264 (AMD)",
    "hevc_amf": "AMF HEVC (AMD)",
    "h264_videotoolbox": "VideoToolbox H.264 (macOS)",
    "hevc_videotoolbox": "VideoToolbox HEVC (macOS)",
    "h264_vaapi": "VAAPI H.264 (Linux)",
    "hevc_vaapi": "VAAPI HEVC (Linux)",
}

_ENCODER_LINE = re.compile(r"^\s*[A-Z.]{6}\s+(\S+)", re.MULTILINE)


def install_hint() -> str:
    import platform

    return INSTALL_HINTS.get(platform.system(), "install FFmpeg from ffmpeg.org")


def find_tool(name: str) -> str | None:
    """Return the resolved path of an executable, or None when not installed."""
    return shutil.which(name)


def run_tool(args: Sequence[str], *, timeout: float = 30.0) -> str:
    """Run a media tool and return its stdout, raising a clear error on failure."""
    command = list(args)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(command[0], install_hint()) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProcessingError(f"{command[0]} timed out after {timeout:.0f}s") from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {completed.returncode}"
        raise ProcessingError(f"{command[0]} failed: {tail}")
    return completed.stdout


def tool_version(executable: str) -> str | None:
    """Return the first line of ``<tool> -version``, or None if it cannot run."""
    try:
        output = run_tool([executable, "-hide_banner", "-version"])
    except ProcessingError as exc:
        LOGGER.debug("could not read version of %s: %s", executable, exc)
        return None
    return output.strip().splitlines()[0].strip() if output.strip() else None


def available_hardware_encoders(ffmpeg: str | None = None) -> tuple[str, ...]:
    """Names of hardware encoders compiled into the ffmpeg binary that was found.

    This reports what the binary *can* do; whether a GPU is actually usable is
    checked at render time in M3 by trying the encoder and falling back.
    """
    executable = ffmpeg or find_tool(FFMPEG)
    if executable is None:
        return ()
    try:
        output = run_tool([executable, "-hide_banner", "-encoders"])
    except ProcessingError as exc:
        LOGGER.debug("could not list encoders: %s", exc)
        return ()

    listed = set(_ENCODER_LINE.findall(output))
    return tuple(name for name in HARDWARE_ENCODERS if name in listed)
