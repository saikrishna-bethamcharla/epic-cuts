"""Find the candidate clip files for a run.

Containers are validated later by ffprobe; this module only decides which files
are worth probing. Files whose extension is not a known media type are listed
as ignored instead of being silently dropped (brief 3.1, 4).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from autocut.errors import InputError
from autocut.ordering.parser import MEDIA_EXTENSIONS

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Discovery:
    """Candidate files in a stable order, plus what was skipped."""

    files: tuple[Path, ...]
    ignored: tuple[Path, ...]


def _is_hidden(relative: Path) -> bool:
    return any(part.startswith(".") for part in relative.parts)


def is_media_candidate(path: Path) -> bool:
    """Known media extension, or no extension at all (ffprobe decides then)."""
    suffix = path.suffix.lower()
    return suffix in MEDIA_EXTENSIONS or suffix == ""


def _iter_directory(directory: Path, *, recursive: bool) -> list[Path]:
    try:
        found = directory.rglob("*") if recursive else directory.glob("*")
        return sorted(path for path in found if path.is_file())
    except OSError as exc:  # pragma: no cover - unreadable drive
        raise InputError(f"cannot list directory {directory}: {exc}") from exc


def discover(inputs: Sequence[Path | str], *, recursive: bool = False) -> Discovery:
    """Expand folders and explicit files into a deduplicated candidate list."""
    if not inputs:
        raise InputError("no input path given")

    files: list[Path] = []
    ignored: list[Path] = []
    seen: set[str] = set()

    def add_file(path: Path) -> None:
        try:
            key = str(path.resolve())
        except OSError:  # pragma: no cover - broken symlink
            key = str(path)
        if key in seen:
            return
        seen.add(key)
        files.append(path)

    for raw in inputs:
        path = Path(raw).expanduser()
        if not path.exists():
            raise InputError(f"input path does not exist: {path}")

        if path.is_dir():
            for child in _iter_directory(path, recursive=recursive):
                if _is_hidden(child.relative_to(path)):
                    continue
                if is_media_candidate(child):
                    add_file(child)
                else:
                    ignored.append(child)
                    LOGGER.debug("ignoring non-media file %s", child)
        else:
            # An explicitly named file is always a candidate.
            add_file(path)

    return Discovery(files=tuple(files), ignored=tuple(ignored))
