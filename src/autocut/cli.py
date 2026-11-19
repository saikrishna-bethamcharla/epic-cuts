"""Command line interface (brief section 7).

``order`` reports, ``analyze`` detects and writes the Cut List, ``run`` does both
and (from M3) renders. Every expected failure becomes one clean line and the
documented exit code.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, ParamSpec, TypeVar

import typer

from autocut import __version__
from autocut.analysis.runner import (
    AnalysisRequest,
    BatchResult,
    analyze_clips,
    default_analysis_cache,
)
from autocut.config import Config, apply_overrides, load_config
from autocut.doctor import build_doctor_report, render_doctor
from autocut.errors import (
    EXIT_OK,
    EXIT_PROCESSING,
    EXIT_WARNINGS,
    AutocutError,
    InputError,
)
from autocut.exporters import (
    DEFAULT_SUFFIX,
    ExportResult,
    export_cutlist,
    infer_format,
    normalise_format,
)
from autocut.logging_utils import configure_logging
from autocut.ordering.plan import OrderingResult, build_ordering
from autocut.ordering.report import (
    format_duration,
    render_human_report,
    write_json_report,
)
from autocut.planning.cutlist import ClipInput, CutList, build_cutlist, write_cutlist
from autocut.planning.loader import CutListSummary, load_cutlist
from autocut.planning.timebase import Timebase
from autocut.render.ffmpeg import ProgressCallback

LOGGER = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    invoke_without_command=True,
    help="Order numbered clips, cut out silence, export editor-ready timelines.",
)

InputArg = Annotated[
    list[Path],
    typer.Argument(metavar="INPUT", help="Clip folder(s) or explicit file(s)."),
]

ConfigOpt = Annotated[Path | None, typer.Option("--config", help="TOML settings file.")]
LogLevelOpt = Annotated[
    str | None, typer.Option("--log-level", help="debug, info, warning, error.")
]
RecursiveOpt = Annotated[
    bool, typer.Option("--recursive", help="Also scan sub-folders.")
]
NumberRuleOpt = Annotated[
    str | None,
    typer.Option("--number-rule", help="natural, first, last, regex."),
]
NumberRegexOpt = Annotated[
    str | None,
    typer.Option("--number-regex", help="Regex whose capture group is the number."),
]
StrictOpt = Annotated[
    bool, typer.Option("--strict", help="Abort on any problem instead of warning.")
]
StrictWarnOpt = Annotated[
    bool, typer.Option("--strict-warnings", help="Exit 1 when problems were found.")
]
DetectorOpt = Annotated[
    str | None, typer.Option("--detector", help="energy (fast) or vad (accurate).")
]
ThresholdOpt = Annotated[
    float | None,
    typer.Option("--threshold-db", help="Energy silence threshold in dBFS."),
]
MinSilenceOpt = Annotated[
    float | None,
    typer.Option("--min-silence", help="Shortest silence to remove, seconds."),
]
MinSpeechOpt = Annotated[
    float | None, typer.Option("--min-speech", help="Shortest speech to keep, seconds.")
]
PadBeforeOpt = Annotated[
    float | None, typer.Option("--pad-before", help="Seconds kept before speech.")
]
PadAfterOpt = Annotated[
    float | None, typer.Option("--pad-after", help="Seconds kept after speech.")
]
ShrinkOpt = Annotated[
    float | None,
    typer.Option(
        "--shrink-pauses-to",
        help="Cap every pause at N seconds instead of removing it entirely.",
    ),
]
TrimOpt = Annotated[
    bool,
    typer.Option("--trim-head-tail", help="Also remove leading and trailing silence."),
]
DenoiseOpt = Annotated[
    bool,
    typer.Option(
        "--denoise-for-analysis",
        help="Denoise a temporary copy used only for detection, never the output.",
    ),
]
AudioTrackOpt = Annotated[
    int | None,
    typer.Option(
        "--audio-track", help="Audio stream index to analyse (default: first)."
    ),
]
PolicyOpt = Annotated[
    str | None,
    typer.Option(
        "--no-audio-policy", help="keep, skip or error for silent/audio-less clips."
    ),
]
JobsOpt = Annotated[
    int | None, typer.Option("--jobs", help="Worker processes (0 = one per core).")
]
FullHashOpt = Annotated[
    bool,
    typer.Option("--full-hash", help="Full SHA-256 instead of the fast fingerprint."),
]
NoCacheOpt = Annotated[
    bool, typer.Option("--no-cache", help="Ignore and do not write the cache.")
]
CacheDirOpt = Annotated[
    Path | None, typer.Option("--cache-dir", help="Where analysis results are cached.")
]
CodecOpt = Annotated[
    str | None,
    typer.Option("--codec", help="Video encoder, e.g. libx264, libx265 or prores_ks."),
]
CrfOpt = Annotated[
    int | None, typer.Option("--crf", help="Quality (lower is better; 0-63).")
]
PresetOpt = Annotated[
    str | None, typer.Option("--preset", help="Encoder speed preset (x264/x265).")
]
AudioBitrateOpt = Annotated[
    str | None, typer.Option("--audio-bitrate", help="Audio bitrate, e.g. 192k.")
]
CrossfadeOpt = Annotated[
    int | None,
    typer.Option("--crossfade-ms", help="Audio fade at every join, in milliseconds."),
]
EncoderOpt = Annotated[
    str | None,
    typer.Option("--encoder", help="Force one encoder, e.g. h264_nvenc."),
]
HardwareOpt = Annotated[
    bool | None,
    typer.Option(
        "--hardware/--no-hardware",
        help="Try hardware encoders before software ones.",
    ),
]
DropFrameOpt = Annotated[
    bool | None,
    typer.Option(
        "--edl-drop-frame/--edl-non-drop",
        help="Drop-frame timecode in the EDL (default: on at 29.97/59.94).",
    ),
]
TitleOpt = Annotated[
    str | None, typer.Option("--title", help="Sequence title recorded in the export.")
]


def guarded(func: Callable[P, R]) -> Callable[P, R]:
    """Turn expected failures into one clean line and the documented exit code."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except AutocutError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(exc.exit_code) from exc
        except KeyboardInterrupt:  # pragma: no cover - interactive use
            typer.secho("cancelled", fg=typer.colors.YELLOW, err=True)
            raise typer.Exit(130) from None

    return wrapper


def _config(
    *,
    config: Path | None,
    log_level: str | None,
    number_rule: str | None,
    number_regex: str | None,
    recursive: bool,
    strict: bool,
    strict_warnings: bool,
    detector: str | None = None,
    threshold_db: float | None = None,
    min_silence: float | None = None,
    min_speech: float | None = None,
    pad_before: float | None = None,
    pad_after: float | None = None,
    shrink_pauses_to: float | None = None,
    trim_head_tail: bool = False,
    denoise: bool = False,
    audio_track: int | None = None,
    no_audio_policy: str | None = None,
    jobs: int | None = None,
    full_hash: bool = False,
    no_cache: bool = False,
    cache_dir: Path | None = None,
    codec: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
    audio_bitrate: str | None = None,
    crossfade_ms: int | None = None,
    encoder: str | None = None,
    hardware: bool | None = None,
    edl_drop_frame: bool | None = None,
) -> Config:
    settings = apply_overrides(
        load_config(config),
        {
            "log.level": log_level,
            "ordering.number_rule": number_rule,
            "ordering.number_regex": number_regex,
            "ordering.recursive": True if recursive else None,
            "run.strict": True if strict else None,
            "run.strict_warnings": True if strict_warnings else None,
            "run.jobs": jobs,
            "run.full_hash": True if full_hash else None,
            "analysis.detector": detector,
            "analysis.threshold_db": threshold_db,
            "analysis.min_silence": min_silence,
            "analysis.min_speech": min_speech,
            "analysis.pad_before": pad_before,
            "analysis.pad_after": pad_after,
            "analysis.shrink_pauses_to": shrink_pauses_to,
            "analysis.trim_head_tail": True if trim_head_tail else None,
            "analysis.denoise_for_analysis": True if denoise else None,
            "analysis.audio_track": audio_track,
            "analysis.no_audio_policy": no_audio_policy,
            "cache.enabled": False if no_cache else None,
            "cache.directory": cache_dir,
            "render.codec": codec,
            "render.crf": crf,
            "render.preset": preset,
            "render.audio_bitrate": audio_bitrate,
            "render.crossfade_ms": crossfade_ms,
            "render.encoder": encoder,
            "render.hardware": hardware,
            "export.edl_drop_frame": edl_drop_frame,
        },
    )
    configure_logging(settings.log.level, settings.log.file)
    return settings


def _order(settings: Config, inputs: list[Path]) -> OrderingResult:
    result = build_ordering(
        inputs,
        number_rule=settings.ordering.number_rule,
        number_regex=settings.ordering.number_regex,
        recursive=settings.ordering.recursive,
        unnumbered_policy=settings.ordering.unnumbered_policy,
    )
    if settings.run.strict and result.problems.has_problems:
        raise InputError(
            f"strict mode: {result.problems.summary()}; "
            "run 'autocut order' to see the full report"
        )
    return result


def _requests(result: OrderingResult) -> list[AnalysisRequest]:
    requests: list[AnalysisRequest] = []
    for item in result.items:
        if item.media is None:
            continue
        requests.append(
            AnalysisRequest(
                path=item.path,
                duration=item.media.duration,
                has_audio=bool(item.media.audio_streams),
            )
        )
    return requests


def _analyse(settings: Config, result: OrderingResult) -> BatchResult:
    cache = default_analysis_cache(
        settings.cache.directory, enabled=settings.cache.enabled
    )
    return analyze_clips(
        _requests(result),
        settings=settings.analysis.to_detector_settings(),
        detector_name=settings.analysis.detector,
        cache=cache,
        jobs=settings.run.jobs,
        policy=settings.analysis.no_audio_policy,
        full_hash=settings.run.full_hash,
    )


def _clip_inputs(result: OrderingResult, batch: BatchResult) -> list[ClipInput]:
    analyses = {analysis.path: analysis for analysis in batch.ok_analyses}
    clips: list[ClipInput] = []
    for item in result.items:
        media = item.media
        if media is None:
            continue
        analysis = analyses.get(item.path)
        if analysis is None:
            continue
        warnings = list(analysis.warnings)
        raw_fps = media.video.fps if media.video is not None else None
        if raw_fps:
            timebase = Timebase.parse(raw_fps)
        else:
            timebase = Timebase.parse("25/1")
            warnings.append("frame rate unknown; assumed 25 fps")
        clips.append(
            ClipInput(
                path=item.path,
                duration=media.duration,
                timebase=timebase,
                segments=tuple(segment.as_tuple() for segment in analysis.segments),
                width=media.video.width if media.video else None,
                height=media.video.height if media.video else None,
                audio_stream=(
                    media.first_audio.index if media.first_audio is not None else None
                ),
                warnings=tuple(warnings),
                source_hash=analysis.fingerprint,
            )
        )
    return clips


def _cutlist(settings: Config, result: OrderingResult, batch: BatchResult) -> CutList:
    clips = _clip_inputs(result, batch)
    if not clips:
        raise InputError("no readable clips to analyse")
    payload = {
        "detector": settings.analysis.detector,
        **settings.analysis.as_cutlist_payload(),
        "number_rule": settings.ordering.number_rule,
        "full_hash": settings.run.full_hash,
    }
    return build_cutlist(clips, settings=payload, full_hash=settings.run.full_hash)


def _report_analysis(batch: BatchResult, cutlist: CutList) -> None:
    analysed = len(batch.ok_analyses)
    typer.echo(
        f"analysed {analysed} clip(s) "
        f"({batch.cached_count} from cache), {len(batch.failures)} failed"
    )
    if batch.ok_analyses:
        detector = batch.ok_analyses[0]
        typer.echo(f"detector: {detector.detector} ({detector.detector_version})")
    typer.echo(
        f"cuts: {cutlist.cut_count}  "
        f"original: {format_duration(cutlist.source_duration)}  "
        f"final: {format_duration(cutlist.duration)}  "
        f"removed: {cutlist.removed_percent}%"
    )
    seen: set[str] = set()
    for analysis in batch.ok_analyses:
        for warning in analysis.warnings:
            if warning not in seen:
                seen.add(warning)
                typer.echo(f"warning: {warning}")
    for path, error in batch.failures:
        typer.echo(f"failed: {path.name}: {error}", err=True)


def _finish(settings: Config, result: OrderingResult, batch: BatchResult) -> None:
    """Apply strict behaviour after the work is done and reported."""
    if batch.failures and settings.run.strict:
        raise InputError(f"strict mode: {len(batch.failures)} clip(s) failed analysis")
    if settings.run.strict_warnings and (
        batch.failures or result.problems.has_problems
    ):
        raise typer.Exit(EXIT_WARNINGS)


def _progress(label: str) -> ProgressCallback:
    """Print a progress line at each 10% step instead of every frame."""
    last = -1

    def report(done: int, total: int) -> None:
        nonlocal last
        if total <= 0:
            return
        step = min(100, done * 100 // total) // 10 * 10
        if step != last:
            last = step
            typer.echo(f"{label}: {step}%")

    return report


def _render(settings: Config, cutlist: Path, target: Path) -> ExportResult:
    loaded = load_cutlist(cutlist)
    result = export_cutlist(
        loaded,
        "render",
        target,
        render_settings=settings.render.to_render_settings(),
        on_progress=_progress("rendering"),
    )
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")
    return result


def _report_export(result: ExportResult, duration: float) -> None:
    if result.format == "render":
        typer.echo(f"rendered {result.path} ({format_duration(duration)})")
        return
    typer.echo(f"exported {result.format}: {result.path} ({format_duration(duration)})")


def _output_path(output: Path) -> Path:
    target = Path(output).expanduser()
    if target.is_dir() or (target.suffix == "" and not target.exists()):
        return target / "cutlist.json"
    return target


@app.callback()
def root(
    version: Annotated[
        bool, typer.Option("--version", help="Print the version and exit.")
    ] = False,
) -> None:
    if version:
        typer.echo(f"autocut {__version__}")
        raise typer.Exit(EXIT_OK)


@app.command()
@guarded
def doctor() -> None:
    """Check ffmpeg, ffprobe and the available hardware encoders."""
    report = build_doctor_report()
    typer.echo(render_doctor(report))
    if not report.ok:
        raise typer.Exit(EXIT_PROCESSING)


@app.command()
@guarded
def order(
    inputs: InputArg,
    json_out: Annotated[
        Path | None,
        typer.Option("--json-out", help="Write the machine-readable report here."),
    ] = None,
    recursive: RecursiveOpt = False,
    number_rule: NumberRuleOpt = None,
    number_regex: NumberRegexOpt = None,
    config: ConfigOpt = None,
    log_level: LogLevelOpt = None,
    strict: StrictOpt = False,
    strict_warnings: StrictWarnOpt = False,
) -> None:
    """Show the numbered order of the clips without processing anything."""
    settings = _config(
        config=config,
        log_level=log_level,
        number_rule=number_rule,
        number_regex=number_regex,
        recursive=recursive,
        strict=strict,
        strict_warnings=strict_warnings,
    )
    result = _order(settings, inputs)
    typer.echo(render_human_report(result))
    if json_out is not None:
        typer.echo(f"wrote {_write_json(result, json_out)}")
    if settings.run.strict_warnings and result.problems.has_problems:
        raise typer.Exit(EXIT_WARNINGS)


@app.command()
@guarded
def analyze(
    inputs: InputArg,
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Cut List JSON file, or a folder."),
    ] = Path("cutlist.json"),
    recursive: RecursiveOpt = False,
    number_rule: NumberRuleOpt = None,
    number_regex: NumberRegexOpt = None,
    detector: DetectorOpt = None,
    threshold_db: ThresholdOpt = None,
    min_silence: MinSilenceOpt = None,
    min_speech: MinSpeechOpt = None,
    pad_before: PadBeforeOpt = None,
    pad_after: PadAfterOpt = None,
    shrink_pauses_to: ShrinkOpt = None,
    trim_head_tail: TrimOpt = False,
    denoise: DenoiseOpt = False,
    audio_track: AudioTrackOpt = None,
    no_audio_policy: PolicyOpt = None,
    jobs: JobsOpt = None,
    full_hash: FullHashOpt = False,
    no_cache: NoCacheOpt = False,
    cache_dir: CacheDirOpt = None,
    config: ConfigOpt = None,
    log_level: LogLevelOpt = None,
    strict: StrictOpt = False,
    strict_warnings: StrictWarnOpt = False,
) -> None:
    """Detect silences and write the Cut List JSON (no export yet)."""
    settings = _config(
        config=config,
        log_level=log_level,
        number_rule=number_rule,
        number_regex=number_regex,
        recursive=recursive,
        strict=strict,
        strict_warnings=strict_warnings,
        detector=detector,
        threshold_db=threshold_db,
        min_silence=min_silence,
        min_speech=min_speech,
        pad_before=pad_before,
        pad_after=pad_after,
        shrink_pauses_to=shrink_pauses_to,
        trim_head_tail=trim_head_tail,
        denoise=denoise,
        audio_track=audio_track,
        no_audio_policy=no_audio_policy,
        jobs=jobs,
        full_hash=full_hash,
        no_cache=no_cache,
        cache_dir=cache_dir,
    )
    result = _order(settings, inputs)
    batch = _analyse(settings, result)
    cutlist = _cutlist(settings, result, batch)
    target = write_cutlist(cutlist, _output_path(output))
    _report_analysis(batch, cutlist)
    typer.echo(f"wrote {target}")
    _finish(settings, result, batch)


@app.command()
@guarded
def run(
    inputs: InputArg,
    output: Annotated[
        Path,
        typer.Option("-o", "--output", help="Output folder (created if missing)."),
    ],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Write the ordering report and stop."),
    ] = False,
    recursive: RecursiveOpt = False,
    number_rule: NumberRuleOpt = None,
    number_regex: NumberRegexOpt = None,
    detector: DetectorOpt = None,
    threshold_db: ThresholdOpt = None,
    min_silence: MinSilenceOpt = None,
    min_speech: MinSpeechOpt = None,
    pad_before: PadBeforeOpt = None,
    pad_after: PadAfterOpt = None,
    shrink_pauses_to: ShrinkOpt = None,
    trim_head_tail: TrimOpt = False,
    denoise: DenoiseOpt = False,
    audio_track: AudioTrackOpt = None,
    no_audio_policy: PolicyOpt = None,
    jobs: JobsOpt = None,
    full_hash: FullHashOpt = False,
    no_cache: NoCacheOpt = False,
    cache_dir: CacheDirOpt = None,
    config: ConfigOpt = None,
    log_level: LogLevelOpt = None,
    strict: StrictOpt = False,
    strict_warnings: StrictWarnOpt = False,
    render_assembly: Annotated[
        bool,
        typer.Option(
            "--render/--no-render",
            help="Render the assembled video after writing the Cut List.",
        ),
    ] = True,
    codec: CodecOpt = None,
    crf: CrfOpt = None,
    preset: PresetOpt = None,
    audio_bitrate: AudioBitrateOpt = None,
    crossfade_ms: CrossfadeOpt = None,
    encoder: EncoderOpt = None,
    hardware: HardwareOpt = None,
) -> None:
    """Order the clips, remove silence, write the Cut List and render it."""
    settings = _config(
        config=config,
        log_level=log_level,
        number_rule=number_rule,
        number_regex=number_regex,
        recursive=recursive,
        strict=strict,
        strict_warnings=strict_warnings,
        detector=detector,
        threshold_db=threshold_db,
        min_silence=min_silence,
        min_speech=min_speech,
        pad_before=pad_before,
        pad_after=pad_after,
        shrink_pauses_to=shrink_pauses_to,
        trim_head_tail=trim_head_tail,
        denoise=denoise,
        audio_track=audio_track,
        no_audio_policy=no_audio_policy,
        jobs=jobs,
        full_hash=full_hash,
        no_cache=no_cache,
        cache_dir=cache_dir,
        codec=codec,
        crf=crf,
        preset=preset,
        audio_bitrate=audio_bitrate,
        crossfade_ms=crossfade_ms,
        encoder=encoder,
        hardware=hardware,
    )
    result = _order(settings, inputs)

    output_dir = Path(output).expanduser()
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise InputError(f"cannot create output folder {output_dir}: {exc}") from exc

    report_text = render_human_report(result)
    text_path = output_dir / "ordering_report.txt"
    json_path = _write_json(result, output_dir / "ordering.json")
    try:
        text_path.write_text(report_text + "\n", encoding="utf-8")
    except OSError as exc:  # pragma: no cover - depends on the filesystem
        raise InputError(f"cannot write {text_path}: {exc}") from exc

    typer.echo(report_text)
    typer.echo("")
    typer.echo(f"wrote {text_path}")
    typer.echo(f"wrote {json_path}")

    if dry_run:
        if settings.run.strict_warnings and result.problems.has_problems:
            raise typer.Exit(EXIT_WARNINGS)
        typer.echo("dry run: stopping before analysis")
        return

    batch = _analyse(settings, result)
    cutlist = _cutlist(settings, result, batch)
    cutlist_path = write_cutlist(cutlist, output_dir / "cutlist.json")
    _report_analysis(batch, cutlist)
    typer.echo(f"wrote {cutlist_path}")
    if render_assembly:
        rendered = _render(settings, cutlist_path, output_dir / "autocut.mp4")
        _report_export(rendered, cutlist.duration)
    _finish(settings, result, batch)


@app.command("export")
@guarded
def export_command(
    cutlist: Annotated[Path, typer.Argument(metavar="CUTLIST.json")],
    format_: Annotated[
        str | None,
        typer.Option(
            "--format",
            help="xmeml, fcpxml, edl or render (inferred from the extension).",
        ),
    ] = None,
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Output file.")
    ] = None,
    title: TitleOpt = None,
    edl_drop_frame: DropFrameOpt = None,
    codec: CodecOpt = None,
    crf: CrfOpt = None,
    preset: PresetOpt = None,
    audio_bitrate: AudioBitrateOpt = None,
    crossfade_ms: CrossfadeOpt = None,
    encoder: EncoderOpt = None,
    hardware: HardwareOpt = None,
    config: ConfigOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Export a Cut List as xmeml, FCPXML, EDL or a rendered video."""
    settings = _config(
        config=config,
        log_level=log_level,
        number_rule=None,
        number_regex=None,
        recursive=False,
        strict=False,
        strict_warnings=False,
        codec=codec,
        crf=crf,
        preset=preset,
        audio_bitrate=audio_bitrate,
        crossfade_ms=crossfade_ms,
        encoder=encoder,
        hardware=hardware,
        edl_drop_frame=edl_drop_frame,
    )
    if format_ is not None:
        export_format = normalise_format(format_)
    elif output is not None:
        export_format = infer_format(output)
    else:
        choices = ", ".join(DEFAULT_SUFFIX)
        raise InputError(
            "pass --format with one of " + choices + ", or an output name whose "
            "extension identifies the format"
        )

    source = Path(cutlist).expanduser()
    target = output or source.with_suffix(DEFAULT_SUFFIX[export_format])
    loaded = load_cutlist(source)
    summary = CutListSummary.of(loaded)
    typer.echo(
        f"cut list: {summary.clips} clip(s), {summary.cuts} cut(s), "
        f"{format_duration(summary.duration)}"
    )
    if summary.missing_sources and export_format != "render":
        typer.echo(
            f"warning: {len(summary.missing_sources)} source clip(s) not found; "
            "the timeline still references them"
        )

    result = export_cutlist(
        loaded,
        export_format,
        target,
        render_settings=settings.render.to_render_settings(),
        title=title or settings.export.title,
        drop_frame=settings.export.edl_drop_frame,
        on_progress=_progress("rendering") if export_format == "render" else None,
    )
    for warning in result.warnings:
        typer.echo(f"warning: {warning}")
    _report_export(result, loaded.duration_seconds)


def _write_json(result: OrderingResult, path: Path) -> Path:
    try:
        return write_json_report(result, path)
    except OSError as exc:
        raise InputError(f"cannot write {path}: {exc}") from exc


def main() -> None:
    """Console-script entry point with a last-resort clean error."""
    try:
        app(prog_name="autocut")
    except AutocutError as exc:  # pragma: no cover - defensive
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise SystemExit(exc.exit_code) from None
