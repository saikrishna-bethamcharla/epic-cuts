"""Command line interface (brief section 7).

``autocut run`` is the end-to-end path; ``order`` only reports; ``analyze`` and
``export`` arrive with M2/M3 and fail with a clear message until then.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, ParamSpec, TypeVar

import typer

from autocut import __version__
from autocut.config import Config, apply_overrides, load_config
from autocut.doctor import build_doctor_report, render_doctor
from autocut.errors import (
    EXIT_OK,
    EXIT_PROCESSING,
    EXIT_WARNINGS,
    AutocutError,
    InputError,
    NotAvailableError,
)
from autocut.logging_utils import configure_logging
from autocut.ordering.plan import OrderingResult, build_ordering
from autocut.ordering.report import render_human_report, write_json_report

LOGGER = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

LATER = (
    "this build covers milestones M0-M1 (setup and ordering). Silence detection "
    "lands in M2 and rendering/exporters in M3-M4; use 'autocut order' or "
    "'autocut run --dry-run' until then"
)

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


def _resolve_config(
    *,
    config: Path | None,
    log_level: str | None,
    number_rule: str | None,
    number_regex: str | None,
    recursive: bool,
    strict: bool,
    strict_warnings: bool,
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


def _warnings_exit(result: OrderingResult, settings: Config) -> None:
    """Exit 1 for warnings, but only when the user asked for it."""
    if settings.run.strict_warnings and result.problems.has_problems:
        raise typer.Exit(EXIT_WARNINGS)


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
    recursive: Annotated[
        bool, typer.Option("--recursive", help="Also scan sub-folders.")
    ] = False,
    number_rule: Annotated[
        str | None,
        typer.Option(
            "--number-rule", help="Which number to use: natural, first, last, regex."
        ),
    ] = None,
    number_regex: Annotated[
        str | None,
        typer.Option("--number-regex", help="Regex whose capture group is the number."),
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="TOML settings file.")
    ] = None,
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="debug, info, warning, error.")
    ] = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Abort on any ordering problem.")
    ] = False,
    strict_warnings: Annotated[
        bool, typer.Option("--strict-warnings", help="Exit 1 when problems exist.")
    ] = False,
) -> None:
    """Show the numbered order of the clips without processing anything."""
    settings = _resolve_config(
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
    _warnings_exit(result, settings)


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
    recursive: Annotated[
        bool, typer.Option("--recursive", help="Also scan sub-folders.")
    ] = False,
    number_rule: Annotated[
        str | None,
        typer.Option(
            "--number-rule", help="Which number to use: natural, first, last, regex."
        ),
    ] = None,
    number_regex: Annotated[
        str | None,
        typer.Option("--number-regex", help="Regex whose capture group is the number."),
    ] = None,
    config: Annotated[
        Path | None, typer.Option("--config", help="TOML settings file.")
    ] = None,
    log_level: Annotated[
        str | None, typer.Option("--log-level", help="debug, info, warning, error.")
    ] = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Abort on any ordering problem.")
    ] = False,
    strict_warnings: Annotated[
        bool, typer.Option("--strict-warnings", help="Exit 1 when problems exist.")
    ] = False,
) -> None:
    """Order the clips, then (from M2) cut silence and export."""
    settings = _resolve_config(
        config=config,
        log_level=log_level,
        number_rule=number_rule,
        number_regex=number_regex,
        recursive=recursive,
        strict=strict,
        strict_warnings=strict_warnings,
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
    _warnings_exit(result, settings)

    if not dry_run:
        raise NotAvailableError(LATER)
    typer.echo("dry run: stopping before analysis")


@app.command()
@guarded
def analyze(
    inputs: InputArg,
    json_out: Annotated[
        Path | None,
        typer.Option("--json-out", help="Where to write the cut list JSON."),
    ] = None,
    recursive: Annotated[bool, typer.Option("--recursive")] = False,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    log_level: Annotated[str | None, typer.Option("--log-level")] = None,
) -> None:
    """Detect silences and write the cut list (M2)."""
    del inputs, json_out, recursive, config, log_level
    raise NotAvailableError(LATER)


@app.command()
@guarded
def export(
    cutlist: Annotated[Path, typer.Argument(metavar="CUTLIST.json")],
    format_: Annotated[
        str,
        typer.Option("--format", help="xmeml, fcpxml, edl or render."),
    ],
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Output file or folder.")
    ] = None,
    config: Annotated[Path | None, typer.Option("--config")] = None,
    log_level: Annotated[str | None, typer.Option("--log-level")] = None,
) -> None:
    """Export a cut list to a timeline or a rendered file (M3-M4)."""
    del cutlist, format_, output, config, log_level
    raise NotAvailableError(LATER)


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
