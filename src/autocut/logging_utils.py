"""Logging setup shared by the CLI and the future local service.

Milestone 5 turns these records into structured (JSON lines) output; the
call sites and level names do not change then.
"""

from __future__ import annotations

import logging
from pathlib import Path

from autocut.errors import InputError

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
VALID_LEVELS = ("debug", "info", "warning", "error", "critical")


def resolve_level(name: str) -> int:
    """Map a level name to a logging constant, rejecting unknown names."""
    key = name.strip().lower()
    if key not in VALID_LEVELS:
        raise InputError(
            f"unknown log level {name!r}; choose one of {', '.join(VALID_LEVELS)}"
        )
    return int(logging.getLevelName(key.upper()))


def configure_logging(level: str = "info", log_file: Path | None = None) -> None:
    """Configure the root logger once, optionally mirroring into a file."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - depends on the filesystem
            raise InputError(f"cannot write log file {log_file}: {exc}") from exc

    logging.basicConfig(
        level=resolve_level(level),
        format=LOG_FORMAT,
        handlers=handlers,
        force=True,
    )
