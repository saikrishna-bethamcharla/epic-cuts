"""ffprobe wrapper: container and stream facts, no decoding.

Containers are identified by probing, never by file extension (brief 3.1).
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autocut.errors import ProbeError, ToolMissingError
from autocut.media.tools import FFPROBE, find_tool, install_hint

LOGGER = logging.getLogger(__name__)

#: Tokens ffprobe reports in ``format_name`` for the containers AutoCut accepts.
SUPPORTED_CONTAINERS: frozenset[str] = frozenset(
    {"mov", "mp4", "m4v", "matroska", "webm", "avi", "mxf"}
)

PROBE_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class VideoStream:
    """First real video stream of a clip."""

    codec: str | None
    width: int | None
    height: int | None
    fps: str | None


@dataclass(frozen=True)
class AudioStream:
    """One audio stream of a clip."""

    index: int
    codec: str | None
    channels: int | None
    sample_rate: int | None


@dataclass(frozen=True)
class MediaInfo:
    """What AutoCut needs to know about a source clip."""

    path: Path
    duration: float
    container: str
    video: VideoStream | None
    audio_streams: tuple[AudioStream, ...]

    @property
    def first_audio(self) -> AudioStream | None:
        return self.audio_streams[0] if self.audio_streams else None

    @property
    def container_tokens(self) -> frozenset[str]:
        return frozenset(token.strip() for token in self.container.split(","))

    @property
    def is_supported_container(self) -> bool:
        return bool(self.container_tokens & SUPPORTED_CONTAINERS)

    @property
    def is_supported(self) -> bool:
        return self.video is not None and self.is_supported_container

    @property
    def resolution(self) -> str | None:
        if self.video is None or self.video.width is None or self.video.height is None:
            return None
        return f"{self.video.width}x{self.video.height}"


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_int(value: object) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _fps(stream: dict[str, Any]) -> str | None:
    for key in ("avg_frame_rate", "r_frame_rate"):
        raw = stream.get(key)
        if isinstance(raw, str) and raw and raw not in {"0/0", "0"}:
            return raw
    return None


def parse_probe_output(path: Path, payload: dict[str, Any]) -> MediaInfo:
    """Turn ffprobe JSON into a :class:`MediaInfo`."""
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ProbeError(str(path), "ffprobe returned no stream information")

    video: VideoStream | None = None
    audio: list[AudioStream] = []
    max_stream_duration: float | None = None

    for stream in streams:
        if not isinstance(stream, dict):
            continue
        stream_duration = _as_float(stream.get("duration"))
        if stream_duration is not None:
            max_stream_duration = max(max_stream_duration or 0.0, stream_duration)

        kind = stream.get("codec_type")
        if kind == "video" and video is None:
            disposition = stream.get("disposition")
            attached = (
                isinstance(disposition, dict) and disposition.get("attached_pic") == 1
            )
            if attached:
                continue
            codec = stream.get("codec_name")
            video = VideoStream(
                codec=codec if isinstance(codec, str) else None,
                width=_as_int(stream.get("width")),
                height=_as_int(stream.get("height")),
                fps=_fps(stream),
            )
        elif kind == "audio":
            codec = stream.get("codec_name")
            audio.append(
                AudioStream(
                    index=_as_int(stream.get("index")) or len(audio),
                    codec=codec if isinstance(codec, str) else None,
                    channels=_as_int(stream.get("channels")),
                    sample_rate=_as_int(stream.get("sample_rate")),
                )
            )

    fmt = payload.get("format")
    container = ""
    duration: float | None = None
    if isinstance(fmt, dict):
        container_raw = fmt.get("format_name")
        container = container_raw if isinstance(container_raw, str) else ""
        duration = _as_float(fmt.get("duration"))

    resolved = duration if duration is not None else max_stream_duration
    if resolved is None or resolved <= 0:
        raise ProbeError(str(path), "duration is unknown (empty or truncated file)")

    return MediaInfo(
        path=path,
        duration=resolved,
        container=container,
        video=video,
        audio_streams=tuple(audio),
    )


def probe_media(path: Path, *, timeout: float = PROBE_TIMEOUT_SECONDS) -> MediaInfo:
    """Probe one file, raising :class:`ProbeError` for anything unreadable."""
    probe = Path(path)
    if not probe.exists():
        raise ProbeError(str(probe), "file does not exist")
    if not probe.is_file():
        raise ProbeError(str(probe), "not a regular file")

    executable = find_tool(FFPROBE)
    if executable is None:
        raise ToolMissingError(FFPROBE, install_hint())

    command = [
        executable,
        "-hide_banner",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-i",
        str(probe),
    ]
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
    except FileNotFoundError as exc:  # pragma: no cover - guarded by find_tool
        raise ToolMissingError(FFPROBE, install_hint()) from exc
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(str(probe), f"ffprobe timed out after {timeout:.0f}s") from exc
    except OSError as exc:
        raise ProbeError(str(probe), f"cannot run ffprobe: {exc}") from exc

    if completed.returncode != 0:
        lines = (completed.stderr or "").strip().splitlines()
        reason = lines[-1] if lines else f"ffprobe exit code {completed.returncode}"
        raise ProbeError(str(probe), reason)

    try:
        payload: object = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ProbeError(str(probe), f"ffprobe output was not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProbeError(str(probe), "ffprobe output was not a JSON object")

    return parse_probe_output(probe, payload)


def probe_safe(path: Path) -> tuple[MediaInfo | None, str | None]:
    """Probe without raising: returns ``(info, None)`` or ``(None, reason)``.

    Ordering uses this so one bad clip is reported instead of aborting the batch.
    """
    try:
        media = probe_media(path)
    except (ProbeError, ToolMissingError) as exc:
        LOGGER.debug("probe failed for %s: %s", path, exc)
        return None, str(exc)
    if not media.is_supported:
        if media.video is None:
            return media, "no video stream (audio-only or image file)"
        return media, f"unsupported container: {media.container or 'unknown'}"
    return media, None
