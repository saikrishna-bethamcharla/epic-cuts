"""Cut List exporters: edit-ready timelines plus the FFmpeg render."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autocut.errors import InputError
from autocut.exporters.edl import build_edl
from autocut.exporters.fcpxml import build_fcpxml
from autocut.exporters.xmeml import build_xmeml
from autocut.planning.loader import LoadedCutList
from autocut.render.ffmpeg import (
    ProgressCallback,
    RenderSettings,
    render_cutlist,
    suggested_output,
)

EXPORT_FORMATS: tuple[str, ...] = ("xmeml", "fcpxml", "edl", "render")
DEFAULT_SUFFIX: dict[str, str] = {
    "xmeml": ".xml",
    "fcpxml": ".fcpxml",
    "edl": ".edl",
    "render": ".mp4",
}
_SUFFIX_FORMAT: dict[str, str] = {
    ".xml": "xmeml",
    ".xmeml": "xmeml",
    ".fcpxml": "fcpxml",
    ".edl": "edl",
    ".mp4": "render",
    ".mov": "render",
    ".mkv": "render",
}


@dataclass(frozen=True)
class ExportResult:
    """Where an export landed and anything the user should know about it."""

    path: Path
    format: str
    warnings: tuple[str, ...] = ()


def normalise_format(name: str) -> str:
    value = name.strip().lower()
    if value == "fcpxml":
        return "fcpxml"
    if value == "xmeml":
        return "xmeml"
    if value not in EXPORT_FORMATS:
        choices = ", ".join(EXPORT_FORMATS)
        raise InputError(f"unknown export format {name!r}; choose one of: {choices}")
    return value


def infer_format(output: Path) -> str:
    """Guess the exporter from the output extension."""
    suffix = output.suffix.lower()
    if suffix in _SUFFIX_FORMAT:
        return _SUFFIX_FORMAT[suffix]
    raise InputError(
        f"cannot infer an export format from {output.name!r}; "
        "pass --format xmeml, fcpxml, edl or render"
    )


def export_cutlist(
    cutlist: LoadedCutList,
    export_format: str,
    output: Path,
    *,
    render_settings: RenderSettings | None = None,
    title: str | None = None,
    drop_frame: bool | None = None,
    on_progress: ProgressCallback | None = None,
) -> ExportResult:
    """Write one export of ``cutlist`` to ``output``."""
    fmt = normalise_format(export_format)
    target = Path(output).expanduser()

    if fmt == "render":
        result = render_cutlist(
            cutlist,
            target,
            render_settings,
            on_progress=on_progress,
        )
        return ExportResult(path=result.output, format=fmt, warnings=result.warnings)

    if fmt == "edl":
        payload = build_edl(cutlist, title=title, drop_frame=drop_frame).encode("utf-8")
    elif fmt == "xmeml":
        payload = build_xmeml(cutlist, title=title)
    else:
        payload = build_fcpxml(cutlist, title=title, drop_frame=drop_frame)

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(payload)
    except OSError as exc:
        raise InputError(f"cannot write {target}: {exc}") from exc
    return ExportResult(path=target, format=fmt)


__all__ = [
    "DEFAULT_SUFFIX",
    "EXPORT_FORMATS",
    "ExportResult",
    "export_cutlist",
    "infer_format",
    "normalise_format",
    "suggested_output",
]
