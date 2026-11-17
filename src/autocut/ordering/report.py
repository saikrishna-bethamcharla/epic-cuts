"""Render an ordering result as text for humans and JSON for machines."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocut import __version__
from autocut.ordering.plan import OrderingResult

ORDERING_SCHEMA_VERSION = 1

_NAME_WIDTH = 38
_NUMBER_WIDTH = 13
_LENGTH_WIDTH = 9


def format_duration(seconds: float | None) -> str:
    """``mm:ss.d`` (or ``h:mm:ss.d`` past an hour); ``-`` when unknown."""
    if seconds is None:
        return "-"
    total = max(0.0, float(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes_int = divmod(int(minutes), 60)
    if hours:
        return f"{hours}:{minutes_int:02d}:{secs:04.1f}"
    return f"{minutes_int:02d}:{secs:04.1f}"


def _shorten(text: str, width: int) -> str:
    if len(text) <= width:
        return text
    return "..." + text[-(width - 3) :]


def render_human_report(result: OrderingResult) -> str:
    """A fixed-width table plus a problem list; ASCII only for any console."""
    inputs = ", ".join(str(path) for path in result.inputs)
    lines = [
        f"AutoCut {__version__} - ordering report",
        f"inputs: {inputs}",
        f"found:  {len(result.items)} clip(s), {len(result.ignored)} ignored file(s)",
        "",
        f"{'#':>3}  {'file':<{_NAME_WIDTH}} {'number':<{_NUMBER_WIDTH}} "
        f"{'length':>{_LENGTH_WIDTH}}  status",
    ]

    for item in result.items:
        number = item.number.describe() if item.number is not None else "-"
        lines.append(
            f"{item.order:>3}  {_shorten(item.filename, _NAME_WIDTH):<{_NAME_WIDTH}} "
            f"{number:<{_NUMBER_WIDTH}} "
            f"{format_duration(item.duration):>{_LENGTH_WIDTH}}  {item.status}"
        )

    if result.problems.has_problems:
        lines.append("")
        lines.append("problems:")
        for gap in result.problems.gaps:
            lines.append(f"  gap         missing clip number(s) {gap.label}")
        for group in result.problems.duplicates:
            lines.append(f"  duplicate   {group.number.raw}: {', '.join(group.files)}")
        for name in result.problems.unnumbered:
            lines.append(f"  no number   {name} (placed at the end)")
        for name, reason in result.problems.unreadable:
            lines.append(f"  unreadable  {name}: {_shorten(reason, 90)}")

    lines.append("")
    if result.items:
        lines.append(
            f"summary: {len(result.items)} clip(s), "
            f"total source length {format_duration(result.total_duration)}, "
            f"{result.problems.summary()}"
        )
    else:
        lines.append("summary: no clips found; check the path and --recursive")
    if result.problems.has_problems:
        lines.append(
            "hint: --strict aborts on these problems, --strict-warnings exits 1"
        )
    return "\n".join(lines)


def render_json_report(result: OrderingResult) -> dict[str, Any]:
    """The machine-readable ordering report (schema version 1)."""
    return {
        "schema_version": ORDERING_SCHEMA_VERSION,
        "generated_by": f"autocut {__version__}",
        "settings": result.settings,
        "inputs": [str(path) for path in result.inputs],
        "clips": [item.to_json() for item in result.items],
        "problems": result.problems.to_json(),
        "ignored": [str(path) for path in result.ignored],
        "summary": {
            "clips": len(result.items),
            "usable_clips": len(result.usable_items),
            "ignored_files": len(result.ignored),
            "total_source_duration": round(result.total_duration, 3),
            "problem_counts": result.problems.counts,
        },
    }


def write_json_report(result: OrderingResult, path: Path) -> Path:
    """Write the JSON report, creating parent folders as needed."""
    target = Path(path).expanduser()
    payload = json.dumps(render_json_report(result), indent=2, ensure_ascii=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(payload + "\n", encoding="utf-8")
    return target
