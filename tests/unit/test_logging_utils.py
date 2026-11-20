"""Text and JSON-Lines logging setup."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.logging_utils import (
    JsonFormatter,
    configure_logging,
    resolve_format,
    resolve_level,
)


def _record(level: int = logging.INFO, message: str = "hello %s") -> logging.LogRecord:
    return logging.LogRecord(
        "autocut.test", level, __file__, 1, message, ("world",), None
    )


def test_json_formatter_emits_one_object_with_extras() -> None:
    record = _record()
    record.clips = 3
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "info"
    assert payload["logger"] == "autocut.test"
    assert payload["clips"] == 3
    assert payload["ts"].endswith("Z")
    assert "\n" not in payload["ts"]


def test_json_formatter_includes_the_traceback() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "autocut.test",
            logging.ERROR,
            __file__,
            1,
            "failed",
            (),
            sys.exc_info(),
        )
    payload = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_json_formatter_ignores_private_attributes() -> None:
    record = _record()
    record._secret = "nope"
    payload = json.loads(JsonFormatter().format(record))
    assert "_secret" not in payload


def test_configure_logging_writes_json_lines(tmp_path: Path) -> None:
    log_file = tmp_path / "logs" / "autocut.jsonl"
    root = logging.getLogger()
    configure_logging("debug", log_file, "json")
    try:
        logging.getLogger("autocut.test").info("ran", extra={"clips": 2})
        for handler in root.handlers:
            handler.flush()
        lines = log_file.read_text(encoding="utf-8").splitlines()
    finally:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)

    payloads = [json.loads(line) for line in lines if line.strip()]
    assert payloads[-1]["message"] == "ran"
    assert payloads[-1]["clips"] == 2


def test_configure_logging_text_format_still_works(tmp_path: Path) -> None:
    log_file = tmp_path / "autocut.log"
    root = logging.getLogger()
    configure_logging("info", log_file, "text")
    try:
        logging.getLogger("autocut.test").info("plain line")
        for handler in root.handlers:
            handler.flush()
        text = log_file.read_text(encoding="utf-8")
    finally:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)

    assert "plain line" in text
    assert "autocut.test" in text
    with pytest.raises(json.JSONDecodeError):
        json.loads(text.splitlines()[0])


def test_unknown_log_format_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="unknown log format"):
        configure_logging("info", tmp_path / "autocut.log", "xml")


def test_resolve_format_is_case_insensitive() -> None:
    assert resolve_format(" JSON ") == "json"
    assert resolve_format("text") == "text"


def test_unknown_log_level_is_rejected() -> None:
    with pytest.raises(InputError, match="unknown log level"):
        resolve_level("loud")
