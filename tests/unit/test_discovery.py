"""Discovery: which files are candidates for probing."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.errors import InputError
from autocut.ordering.discovery import discover, is_media_candidate
from tests.conftest import make_clips


def test_media_candidate_accepts_known_extensions_and_extensionless_files() -> None:
    assert is_media_candidate(Path("a.MP4"))
    assert is_media_candidate(Path("a.mxf"))
    assert is_media_candidate(Path("clip1"))
    assert not is_media_candidate(Path("notes.txt"))
    assert not is_media_candidate(Path("a.wav"))


def test_non_media_files_are_ignored_not_dropped(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "notes.txt", "project.xmeml"])
    found = discover([tmp_path])
    assert [path.name for path in found.files] == ["1.mp4"]
    assert [path.name for path in found.ignored] == ["notes.txt", "project.xmeml"]


def test_hidden_files_and_folders_are_skipped(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", ".hidden2.mp4"])
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "3.mp4").write_bytes(b"")
    found = discover([tmp_path], recursive=True)
    assert [path.name for path in found.files] == ["1.mp4"]


def test_recursive_flag_reaches_subfolders(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    make_clips(tmp_path / "day2", ["2.mp4"])

    flat = discover([tmp_path])
    assert [path.name for path in flat.files] == ["1.mp4"]

    deep = discover([tmp_path], recursive=True)
    assert sorted(path.name for path in deep.files) == ["1.mp4", "2.mp4"]


def test_explicit_file_is_always_a_candidate(tmp_path: Path) -> None:
    target = tmp_path / "weird.wav"
    target.write_bytes(b"")
    found = discover([target])
    assert [path.name for path in found.files] == ["weird.wav"]


def test_duplicate_inputs_are_deduplicated(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    found = discover([tmp_path, tmp_path / "1.mp4", tmp_path])
    assert len(found.files) == 1


def test_missing_path_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        discover([tmp_path / "missing"])


def test_no_inputs_is_an_input_error() -> None:
    with pytest.raises(InputError, match="no input path"):
        discover([])
