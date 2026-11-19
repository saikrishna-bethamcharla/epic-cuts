"""Analysis cache keys, entries and failure tolerance."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autocut.analysis.cache import (
    AnalysisCache,
    CachedAnalysis,
    default_cache_root,
)

BASE_KEY_ARGS: dict[str, object] = {
    "fingerprint": "fast:100:1:abc",
    "detector": "energy",
    "detector_version": "1",
    "settings": {"threshold_db": -35.0},
    "duration": 12.5,
    "has_audio": True,
}


def make_key(**overrides: object) -> str:
    merged = {**BASE_KEY_ARGS, **overrides}
    return AnalysisCache.make_key(**merged)  # type: ignore[arg-type]


def test_keys_are_stable_for_identical_inputs() -> None:
    assert make_key() == make_key()
    assert make_key(settings={"threshold_db": -35.0, "min_silence": 0.5}) == make_key(
        settings={"min_silence": 0.5, "threshold_db": -35.0}
    )


def test_keys_change_with_every_input() -> None:
    base = make_key()
    assert make_key(fingerprint="other") != base
    assert make_key(detector="vad") != base
    assert make_key(detector_version="2") != base
    assert make_key(settings={"threshold_db": -20.0}) != base
    assert make_key(duration=12.6) != base
    assert make_key(has_audio=False) != base


def test_store_and_load_roundtrip(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path)
    key = make_key()
    cached = CachedAnalysis(segments=((0.0, 1.5), (2.0, 3.25)), warnings=("hi",))
    cache.store(key, cached)

    loaded = cache.load(key)
    assert loaded is not None
    assert loaded.segments == ((0.0, 1.5), (2.0, 3.25))
    assert loaded.warnings == ("hi",)
    assert [segment.as_tuple() for segment in loaded.as_segments()] == [
        (0.0, 1.5),
        (2.0, 3.25),
    ]


def test_missing_entry_is_none(tmp_path: Path) -> None:
    assert AnalysisCache(tmp_path).load(make_key()) is None


def test_disabled_cache_neither_reads_nor_writes(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path, enabled=False)
    key = make_key()
    cache.store(key, CachedAnalysis(segments=((0.0, 1.0),)))
    assert not cache.path_for(key).exists()
    assert cache.load(key) is None


def test_corrupt_entry_is_ignored(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path)
    key = make_key()
    cache.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    cache.path_for(key).write_text("{not json", encoding="utf-8")
    assert cache.load(key) is None


def test_entry_with_unknown_schema_is_ignored(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path)
    key = make_key()
    cache.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    cache.path_for(key).write_text(
        json.dumps({"schema_version": 99, "segments": []}), encoding="utf-8"
    )
    assert cache.load(key) is None


def test_non_object_entry_is_ignored(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path)
    key = make_key()
    cache.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    cache.path_for(key).write_text("[1, 2, 3]", encoding="utf-8")
    assert cache.load(key) is None


def test_entry_with_junk_segments_loads_what_it_can(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path)
    key = make_key()
    cache.path_for(key).parent.mkdir(parents=True, exist_ok=True)
    cache.path_for(key).write_text(
        json.dumps(
            {
                "schema_version": 1,
                "segments": [[0.0, 1.0], [5.0], "nope"],
                "warnings": ["w"],
            }
        ),
        encoding="utf-8",
    )
    loaded = cache.load(key)
    assert loaded is not None
    assert loaded.segments == ((0.0, 1.0),)


def test_cache_root_honours_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOCUT_CACHE_DIR", str(tmp_path / "custom"))
    assert default_cache_root() == tmp_path / "custom"


def test_cache_writes_are_atomic_enough_to_create_folders(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path / "deep" / "nested")
    key = make_key()
    cache.store(key, CachedAnalysis(segments=((0.0, 1.0),)))
    assert cache.path_for(key).exists()
