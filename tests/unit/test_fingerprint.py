"""Fast fingerprints and the ``--full-hash`` alternative."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.media.fingerprint import FAST_WINDOW_BYTES, file_fingerprint


def write_sized(path: Path, size: int, fill: bytes = b"\0") -> Path:
    path.write_bytes(fill * size)
    return path


def test_fingerprint_is_stable_for_an_unchanged_file(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 1024)
    assert file_fingerprint(target) == file_fingerprint(target)


def test_fingerprint_changes_when_the_tail_changes(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 9 * 1024 * 1024)
    before = file_fingerprint(target)
    with target.open("r+b") as handle:
        handle.seek(-1, os.SEEK_END)
        handle.write(b"\xff")
    assert file_fingerprint(target) != before


def test_fingerprint_changes_when_the_head_changes(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 64)
    before = file_fingerprint(target)
    with target.open("r+b") as handle:
        handle.write(b"\xff")
    assert file_fingerprint(target) != before


def test_fingerprint_includes_mtime(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 64)
    before = file_fingerprint(target)
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
    assert file_fingerprint(target) != before


def test_fingerprint_format_documents_its_parts(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 64)
    fingerprint = file_fingerprint(target)
    kind, size, mtime_ns, digest = fingerprint.split(":")
    assert kind == "fast"
    assert size == "64"
    assert int(mtime_ns) > 0
    assert len(digest) == 32


def test_middle_edits_are_invisible_to_the_fast_mode_but_not_the_full_hash(
    tmp_path: Path,
) -> None:
    """Documented trade-off: the fast mode samples the head and the tail only."""
    target = write_sized(tmp_path / "big.mp4", 9 * 1024 * 1024)
    stat = target.stat()
    fast_before = file_fingerprint(target)
    full_before = file_fingerprint(target, full_hash=True)

    with target.open("r+b") as handle:
        handle.seek(FAST_WINDOW_BYTES + 1024)
        handle.write(b"\xff")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    assert file_fingerprint(target) == fast_before
    assert file_fingerprint(target, full_hash=True) != full_before


def test_full_hash_ignores_mtime_and_starts_with_sha256(tmp_path: Path) -> None:
    target = write_sized(tmp_path / "a.mp4", 128)
    before = file_fingerprint(target, full_hash=True)
    assert before.startswith("sha256:")
    os.utime(target, ns=(1_000_000_000, 1_000_000_000))
    assert file_fingerprint(target, full_hash=True) == before


def test_missing_file_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="cannot read"):
        file_fingerprint(tmp_path / "nope.mp4")
