"""Render a Cut List to one file with FFmpeg.

The timeline is rebuilt with ``trim``/``atrim`` and the ``concat`` filter, which
is frame-accurate (frame indices, not decimal seek positions) and handles
mixed-resolution and mixed-rate sources in a single pass. Audio segments get a
short fade in and out (``crossfade_ms``) so joins do not click.

Hardware encoders are tried first when enabled and available, then the software
encoder; a GPU that advertises an encoder but cannot actually run falls back
transparently instead of failing the render.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from autocut.errors import InputError, ProcessingError, ToolMissingError
from autocut.media.probe import MediaInfo, probe_media
from autocut.media.tools import (
    FFMPEG,
    available_hardware_encoders,
    find_tool,
    install_hint,
)
from autocut.planning.loader import LoadedCutList

LOGGER = logging.getLogger(__name__)

ProgressCallback = Callable[[int, int], None]

_H264_HARDWARE = ("h264_nvenc", "h264_qsv", "h264_amf", "h264_videotoolbox")
_HEVC_HARDWARE = ("hevc_nvenc", "hevc_qsv", "hevc_amf", "hevc_videotoolbox")
_SOFTWARE = {
    "h264_nvenc": "libx264",
    "h264_qsv": "libx264",
    "h264_amf": "libx264",
    "h264_videotoolbox": "libx264",
    "hevc_nvenc": "libx265",
    "hevc_qsv": "libx265",
    "hevc_amf": "libx265",
    "hevc_videotoolbox": "libx265",
}


@dataclass(frozen=True)
class RenderSettings:
    """Encoder and assembly choices for one render."""

    codec: str = "libx264"
    crf: int = 18
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    crossfade_ms: int = 10
    hardware: bool = True
    faststart: bool = True
    encoder: str | None = None
    threads: int | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.crf <= 63:
            raise InputError(f"crf must be between 0 and 63, not {self.crf}")
        if self.crossfade_ms < 0:
            raise InputError("crossfade_ms must not be negative")


@dataclass(frozen=True)
class RenderPlan:
    """The FFmpeg inputs and filter graph for one Cut List."""

    inputs: tuple[Path, ...]
    filter_graph: str
    total_frames: int
    has_audio: bool


@dataclass(frozen=True)
class RenderResult:
    """What a successful render produced."""

    output: Path
    encoder: str
    frames: int
    duration: float
    fell_back: bool = False
    warnings: tuple[str, ...] = ()


def _software_codec(codec: str) -> str:
    if codec in _SOFTWARE:
        return _SOFTWARE[codec]
    if codec.startswith("h264"):
        return "libx264"
    if codec.startswith("hevc") or codec == "libx265":
        return "libx265"
    return codec


def encoder_candidates(
    settings: RenderSettings, available: Sequence[str]
) -> tuple[str, ...]:
    """Encoders to try, best first, always ending with a software encoder."""
    software = _software_codec(settings.codec)
    if settings.encoder:
        return tuple(dict.fromkeys((settings.encoder, software)))
    if not settings.hardware or software not in {"libx264", "libx265"}:
        return (software,)

    family = _H264_HARDWARE if software == "libx264" else _HEVC_HARDWARE
    present = set(available)
    hardware = tuple(name for name in family if name in present)
    return tuple(dict.fromkeys((*hardware, software)))


def _fade_chain(duration: float, crossfade_ms: int) -> str:
    fade = min(crossfade_ms / 1000.0, duration / 2.0)
    if fade <= 0:
        return ""
    return (
        f",afade=t=in:st=0:d={fade:.6f}"
        f",afade=t=out:st={duration - fade:.6f}:d={fade:.6f}"
    )


def build_plan(
    cutlist: LoadedCutList,
    *,
    crossfade_ms: int = 10,
    audio_ordinals: Mapping[int, int | None] | None = None,
) -> RenderPlan:
    """Build the FFmpeg filter graph for every keep segment in the Cut List."""
    active = [clip for clip in cutlist.clips if clip.segments]
    if not active:
        raise InputError("cut list contains no segments to render")

    ordinals: dict[int, int | None] = {}
    for clip in active:
        if audio_ordinals is not None:
            ordinals[clip.order] = audio_ordinals.get(clip.order)
        elif clip.audio_stream is not None:
            ordinals[clip.order] = 0
        else:
            ordinals[clip.order] = None
    has_audio = any(ordinal is not None for ordinal in ordinals.values())

    inputs: list[Path] = []
    chains: list[str] = []
    pairs: list[str] = []
    video_only: list[str] = []
    for index, clip in enumerate(active):
        inputs.append(clip.source_path)
        ordinal = ordinals[clip.order]
        for number, segment in enumerate(clip.segments):
            duration = clip.timebase.seconds(
                segment.src_out_frame - segment.src_in_frame
            )
            video_label = f"v{index}_{number}"
            audio_label = f"a{index}_{number}"
            chains.append(
                f"[{index}:v:0]trim=start_frame={segment.src_in_frame}:"
                f"end_frame={segment.src_out_frame},setpts=PTS-STARTPTS,"
                f"fps={cutlist.timebase.num}/{cutlist.timebase.den},"
                f"scale={cutlist.width}:{cutlist.height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad={cutlist.width}:{cutlist.height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,format=yuv420p,settb=AVTB[{video_label}]"
            )
            video_only.append(f"[{video_label}]")
            if not has_audio:
                continue
            if ordinal is None:
                chains.append(
                    f"anullsrc=channel_layout=stereo:"
                    f"sample_rate={cutlist.audio_rate},"
                    f"atrim=duration={duration:.6f},asetpts=PTS-STARTPTS"
                    f"{_fade_chain(duration, crossfade_ms)}[{audio_label}]"
                )
            else:
                chains.append(
                    f"[{index}:a:{ordinal}]atrim=start="
                    f"{clip.timebase.seconds(segment.src_in_frame):.6f}:end="
                    f"{clip.timebase.seconds(segment.src_out_frame):.6f},"
                    f"asetpts=PTS-STARTPTS,aresample={cutlist.audio_rate},"
                    "aformat=sample_fmts=fltp:channel_layouts=stereo"
                    f"{_fade_chain(duration, crossfade_ms)}[{audio_label}]"
                )
            pairs.append(f"[{video_label}][{audio_label}]")

    segments = len(video_only)
    if has_audio:
        join = "".join(pairs) + f"concat=n={segments}:v=1:a=1[vout][aout]"
    else:
        join = "".join(video_only) + f"concat=n={segments}:v=1:a=0[vout]"
    return RenderPlan(
        inputs=tuple(inputs),
        filter_graph=";".join([*chains, join]),
        total_frames=cutlist.total_frames,
        has_audio=has_audio,
    )


def _quality_args(encoder: str, settings: RenderSettings) -> list[str]:
    if encoder in {"libx264", "libx265"}:
        return ["-crf", str(settings.crf), "-preset", settings.preset]
    if encoder == "h264_nvenc" or encoder == "hevc_nvenc":
        return ["-rc", "vbr", "-cq", str(settings.crf), "-b:v", "0"]
    if encoder.endswith("_qsv"):
        return ["-global_quality", str(settings.crf)]
    if encoder.endswith("_amf"):
        return ["-rc", "cqp", "-qp_i", str(settings.crf), "-qp_p", str(settings.crf)]
    if encoder.endswith("_videotoolbox"):
        return ["-q:v", str(max(1, min(100, 100 - settings.crf)))]
    return []


def build_render_command(
    plan: RenderPlan,
    output: Path,
    settings: RenderSettings,
    encoder: str,
) -> list[str]:
    """The complete FFmpeg argument list for one encoder attempt."""
    executable = find_tool(FFMPEG) or FFMPEG
    command = [
        executable,
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
    ]
    for source in plan.inputs:
        command += ["-i", str(source)]
    command += ["-filter_complex", plan.filter_graph, "-map", "[vout]"]
    if plan.has_audio:
        command += ["-map", "[aout]", "-c:a", settings.audio_codec]
        if settings.audio_bitrate:
            command += ["-b:a", settings.audio_bitrate]
    command += ["-c:v", encoder, *_quality_args(encoder, settings)]
    if encoder in {"libx264", "libx265"}:
        command += ["-pix_fmt", "yuv420p"]
    if settings.threads is not None:
        command += ["-threads", str(settings.threads)]
    if settings.faststart and output.suffix.lower() in {".mp4", ".mov", ".m4v"}:
        command += ["-movflags", "+faststart"]
    command.append(str(output))
    return command


def _run_ffmpeg(
    command: Sequence[str],
    *,
    total_frames: int,
    fps: float,
    on_progress: ProgressCallback | None,
) -> None:
    try:
        process = subprocess.Popen(
            list(command),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as exc:  # pragma: no cover - guarded by find_tool
        raise ToolMissingError(FFMPEG, install_hint()) from exc

    stderr_lines: list[str] = []

    def drain() -> None:
        if process.stderr is None:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    reported = -1
    try:
        if process.stdout is not None:
            for line in process.stdout:
                if not line.startswith("out_time_us="):
                    continue
                try:
                    microseconds = int(line.split("=", 1)[1].strip())
                except ValueError:
                    continue
                if microseconds < 0 or on_progress is None:
                    continue
                frames = min(total_frames, int(microseconds / 1_000_000 * fps))
                if frames != reported:
                    reported = frames
                    on_progress(frames, total_frames)
        return_code = process.wait()
    except KeyboardInterrupt:
        process.kill()
        process.wait()
        raise
    finally:
        reader.join(timeout=5)
        if process.poll() is None:  # pragma: no cover - defensive
            process.kill()

    if return_code != 0:
        tail = stderr_lines[-3:] if stderr_lines else ["ffmpeg exited unexpectedly"]
        raise ProcessingError("ffmpeg render failed: " + " | ".join(tail))


def _audio_ordinals(cutlist: LoadedCutList) -> dict[int, int | None]:
    probes: dict[Path, MediaInfo] = {}
    ordinals: dict[int, int | None] = {}
    for clip in cutlist.clips:
        if not clip.segments:
            continue
        if clip.audio_stream is None:
            ordinals[clip.order] = None
            continue
        info = probes.get(clip.source_path)
        if info is None:
            info = probe_media(clip.source_path)
            probes[clip.source_path] = info
        position = next(
            (
                index
                for index, stream in enumerate(info.audio_streams)
                if stream.index == clip.audio_stream
            ),
            None,
        )
        if position is None:
            raise InputError(
                f"{clip.source_path.name} has no audio stream "
                f"{clip.audio_stream} recorded in the cut list"
            )
        ordinals[clip.order] = position
    return ordinals


def _discard_partial(path: Path) -> None:
    """Remove an incomplete render so no half file is mistaken for a result."""
    try:
        if path.exists():
            path.unlink()
    except OSError:  # pragma: no cover - depends on the filesystem
        LOGGER.debug("could not remove partial output %s", path)


def render_cutlist(
    cutlist: LoadedCutList,
    output: Path,
    settings: RenderSettings | None = None,
    *,
    on_progress: ProgressCallback | None = None,
) -> RenderResult:
    """Render every keep segment to ``output``, falling back to software."""
    settings = settings or RenderSettings()
    target = Path(output).expanduser()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        raise InputError(f"cannot create output folder {target.parent}: {exc}") from exc

    missing = cutlist.missing_sources()
    if missing:
        names = ", ".join(path.name for path in missing[:3])
        more = "" if len(missing) <= 3 else f" (+{len(missing) - 3} more)"
        raise InputError(f"source clip(s) not found: {names}{more}")

    plan = build_plan(
        cutlist,
        crossfade_ms=settings.crossfade_ms,
        audio_ordinals=_audio_ordinals(cutlist),
    )
    candidates = encoder_candidates(settings, available_hardware_encoders())
    failures: list[str] = []

    try:
        for encoder in candidates:
            command = build_render_command(plan, target, settings, encoder)
            LOGGER.debug("rendering with %s: %s", encoder, command)
            try:
                _run_ffmpeg(
                    command,
                    total_frames=plan.total_frames,
                    fps=cutlist.timebase.fps,
                    on_progress=on_progress,
                )
            except ProcessingError as exc:
                failures.append(f"{encoder}: {exc}")
                _discard_partial(target)
                continue
            if not target.exists() or target.stat().st_size == 0:
                failures.append(f"{encoder}: ffmpeg produced no output")
                continue
            fell_back = encoder != candidates[0]
            warnings: tuple[str, ...] = ()
            if fell_back:
                warnings = (f"{candidates[0]} failed; rendered with {encoder}",)
                LOGGER.warning(
                    "encoder fallback",
                    extra={"preferred": candidates[0], "used": encoder},
                )
            LOGGER.info(
                "render complete",
                extra={
                    "encoder": encoder,
                    "frames": plan.total_frames,
                    "seconds": round(cutlist.duration_seconds, 3),
                    "fallback": fell_back,
                },
            )
            return RenderResult(
                output=target,
                encoder=encoder,
                frames=plan.total_frames,
                duration=cutlist.duration_seconds,
                fell_back=fell_back,
                warnings=warnings,
            )
    except BaseException:
        # A cancelled or crashed render must not leave a playable-looking stub.
        _discard_partial(target)
        raise

    _discard_partial(target)
    raise ProcessingError("render failed: " + "; ".join(failures))


def suggested_output(path: Path) -> Path:
    """Default render target next to a Cut List."""
    return Path(path).expanduser().with_suffix(".mp4")
