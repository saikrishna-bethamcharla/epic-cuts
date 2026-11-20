"""Logging setup shared by the CLI and the future local service.

Two formats: the human text line used from M1 and JSON Lines for machines
(DECISIONS D31). Call sites only ever pass ``extra={...}``: the text formatter
ignores those fields and the JSON formatter turns them into top-level keys, so
no logging call has to change when the format does.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from autocut.errors import InputError

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
VALID_LEVELS = ("debug", "info", "warning", "error", "critical")
LogFormat = Literal["text", "json"]
VALID_FORMATS: tuple[str, ...] = ("text", "json")

#: ``LogRecord`` attributes that are not user-supplied ``extra`` fields.
_RESERVED_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


def resolve_level(name: str) -> int:
    """Map a level name to a logging constant, rejecting unknown names."""
    key = name.strip().lower()
    if key not in VALID_LEVELS:
        raise InputError(
            f"unknown log level {name!r}; choose one of {', '.join(VALID_LEVELS)}"
        )
    return int(logging.getLevelName(key.upper()))


def resolve_format(name: str) -> LogFormat:
    """Map a format name to the formatter to use, rejecting unknown names."""
    key = name.strip().lower()
    if key not in VALID_FORMATS:
        raise InputError(
            f"unknown log format {name!r}; choose one of {', '.join(VALID_FORMATS)}"
        )
    return "json" if key == "json" else "text"


class JsonFormatter(logging.Formatter):
    """One JSON object per line: timestamp, level, logger, message and extras."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_FIELDS or key.startswith("_"):
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    level: str = "info",
    log_file: Path | None = None,
    fmt: str = "text",
) -> None:
    """Configure the root logger once, optionally mirroring into a file."""
    formatter: logging.Formatter = (
        JsonFormatter()
        if resolve_format(fmt) == "json"
        else logging.Formatter(LOG_FORMAT)
    )
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
        except OSError as exc:  # pragma: no cover - depends on the filesystem
            raise InputError(f"cannot write log file {log_file}: {exc}") from exc
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(
        level=resolve_level(level),
        handlers=handlers,
        force=True,
    )
