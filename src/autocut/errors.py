"""Expected failure types, each mapped to a documented CLI exit code.

Exit codes (brief section 7): 0 success, 1 warnings under ``--strict-warnings``,
2 user input error, 3 processing error.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_INPUT = 2
EXIT_PROCESSING = 3


class AutocutError(Exception):
    """Base class for every failure the user is meant to read."""

    exit_code: int = EXIT_PROCESSING

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class InputError(AutocutError):
    """Bad arguments, missing paths, invalid config or filename rules."""

    exit_code = EXIT_INPUT


class ProcessingError(AutocutError):
    """A step failed while working on media."""

    exit_code = EXIT_PROCESSING


class ToolMissingError(ProcessingError):
    """A required external tool (ffmpeg/ffprobe) is not installed."""

    def __init__(self, tool: str, install_hint: str) -> None:
        super().__init__(
            f"{tool} was not found on PATH. Install FFmpeg and make sure both "
            f"ffmpeg and ffprobe are callable. {install_hint}"
        )
        self.tool = tool


class ProbeError(ProcessingError):
    """ffprobe could not read a file."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"could not read media file {path}: {reason}")
        self.path = path
        self.reason = reason


class NotAvailableError(ProcessingError):
    """A milestone feature that this build does not include yet."""


class CancelledError(AutocutError):
    """The operation was cancelled (used by the engine API from M7 onwards)."""

    exit_code = 130
