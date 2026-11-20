"""``autocut analyze`` end to end, including cache behaviour and policies."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from autocut.cli import app
from tests.media_fixtures import tone_bursts, video_clip, wav_duration

runner = CliRunner()


def make_clip(
    directory: Path,
    name: str,
    *,
    speech: float = 1.0,
    silence: float = 1.0,
    repeats: int = 3,
    audio: bool = True,
) -> Path:
    target = directory / name
    if not audio:
        return video_clip(target, audio=None, seconds=2.0)
    wav = tone_bursts(
        directory / f"{name}.wav", speech=speech, silence=silence, repeats=repeats
    )
    return video_clip(target, audio=wav, seconds=wav_duration(wav))


def test_analyze_profile_is_recorded_in_the_cutlist(
    clips: Path, tmp_path: Path
) -> None:
    out = tmp_path / "cutlist.json"
    result = run_analyze(
        str(clips),
        "-o",
        str(out),
        "--detector",
        "energy",
        "--no-cache",
        "--profile",
        "aggressive",
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["settings"]["profile"] == "aggressive"
    assert payload["settings"]["min_silence"] == pytest.approx(0.25)
    assert payload["settings"]["pad_after"] == pytest.approx(0.10)


def test_analyze_json_logs_a_structured_summary(clips: Path, tmp_path: Path) -> None:
    log_file = tmp_path / "autocut.jsonl"
    config = tmp_path / "autocut.toml"
    config.write_text(
        '[log]\nformat = "json"\n' + f'file = "{log_file.as_posix()}"\n',
        encoding="utf-8",
    )
    result = run_analyze(
        str(clips),
        "-o",
        str(tmp_path / "cutlist.json"),
        "--detector",
        "energy",
        "--no-cache",
        "--config",
        str(config),
    )
    assert result.exit_code == 0, result.stderr

    root = logging.getLogger()
    try:
        records = [
            json.loads(line)
            for line in log_file.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    finally:
        for handler in list(root.handlers):
            handler.close()
            root.removeHandler(handler)

    summary = next(r for r in records if r["message"] == "analysis complete")
    assert summary["level"] == "info"
    assert summary["clips"] == 2
    assert summary["failed"] == 0
    assert summary["cuts"] >= 4
    assert summary["removed_percent"] > 0


@pytest.fixture
def clips(tmp_path: Path) -> Path:
    folder = tmp_path / "clips"
    folder.mkdir()
    make_clip(folder, "01.mp4")
    make_clip(folder, "02.mp4")
    return folder


def run_analyze(*args: str) -> Any:
    return runner.invoke(app, ["analyze", *args])


def test_analyze_writes_a_frame_canonical_cutlist(clips: Path, tmp_path: Path) -> None:
    out = tmp_path / "cutlist.json"
    result = run_analyze(
        str(clips),
        "-o",
        str(out),
        "--detector",
        "energy",
        "--no-cache",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["settings"]["detector"] == "energy"
    assert payload["sequence"]["fps"]
    assert len(payload["clips"]) == 2
    assert payload["timeline"]["cuts"] >= 4
    assert 10.0 <= payload["timeline"]["removed_percent"] <= 45.0

    cursor = 0
    for clip in payload["clips"]:
        for segment in clip["segments"]:
            assert segment["rec_in_frame"] == cursor
            assert (
                segment["frames"] == segment["rec_out_frame"] - segment["rec_in_frame"]
            )
            cursor = segment["rec_out_frame"]
    assert payload["timeline"]["frames"] == cursor
    assert "removed:" in result.stdout


def test_second_run_uses_the_cache(clips: Path, tmp_path: Path) -> None:
    cache = str(tmp_path / "cache")
    args = (
        str(clips),
        "-o",
        str(tmp_path / "out.json"),
        "--detector",
        "energy",
        "--cache-dir",
        cache,
    )
    first = run_analyze(*args)
    second = run_analyze(*args)
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert "0 from cache" in first.stdout
    assert "2 from cache" in second.stdout


def test_no_cache_forces_fresh_work(clips: Path, tmp_path: Path) -> None:
    args = (
        str(clips),
        "-o",
        str(tmp_path / "out.json"),
        "--detector",
        "energy",
        "--no-cache",
        "--cache-dir",
        str(tmp_path / "cache"),
    )
    run_analyze(*args)
    second = run_analyze(*args)
    assert "0 from cache" in second.stdout


def test_jobs_flag_is_accepted(clips: Path, tmp_path: Path) -> None:
    result = run_analyze(
        str(clips),
        "-o",
        str(tmp_path / "out.json"),
        "--detector",
        "energy",
        "--jobs",
        "2",
        "--no-cache",
    )
    assert result.exit_code == 0, result.stderr


def test_silent_clip_honours_no_audio_policy(tmp_path: Path) -> None:
    folder = tmp_path / "silent"
    folder.mkdir()
    make_clip(folder, "01.mp4", audio=False)

    kept = run_analyze(
        str(folder),
        "-o",
        str(tmp_path / "kept.json"),
        "--detector",
        "energy",
        "--no-cache",
    )
    assert kept.exit_code == 0, kept.stderr
    assert "no audio track" in kept.stdout
    payload = json.loads((tmp_path / "kept.json").read_text(encoding="utf-8"))
    assert payload["clips"][0]["segments"]
    assert payload["timeline"]["removed_percent"] == 0.0

    skipped = run_analyze(
        str(folder),
        "-o",
        str(tmp_path / "skipped.json"),
        "--detector",
        "energy",
        "--no-cache",
        "--no-audio-policy",
        "skip",
    )
    assert skipped.exit_code == 0, skipped.stderr
    payload = json.loads((tmp_path / "skipped.json").read_text(encoding="utf-8"))
    assert payload["clips"][0]["segments"] == []


def test_full_hash_is_recorded_in_the_cutlist(clips: Path, tmp_path: Path) -> None:
    out = tmp_path / "hashed.json"
    result = run_analyze(
        str(clips), "-o", str(out), "--detector", "energy", "--no-cache", "--full-hash"
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["clips"][0]["source_hash"].startswith("sha256:")
    assert payload["settings"]["full_hash"] is True


def test_trim_head_tail_changes_the_result(clips: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain.json"
    trimmed = tmp_path / "trimmed.json"
    run_analyze(str(clips), "-o", str(plain), "--detector", "energy", "--no-cache")
    run_analyze(
        str(clips),
        "-o",
        str(trimmed),
        "--detector",
        "energy",
        "--no-cache",
        "--trim-head-tail",
    )
    full = json.loads(plain.read_text(encoding="utf-8"))["timeline"]["duration"]
    short = json.loads(trimmed.read_text(encoding="utf-8"))["timeline"]["duration"]
    assert short < full


def test_analyze_on_empty_folder_is_an_input_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run_analyze(str(empty), "-o", str(tmp_path / "out.json"))
    assert result.exit_code == 2
    assert "no readable clips" in result.stderr


def test_run_writes_the_cutlist_and_renders(clips: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            str(clips),
            "-o",
            str(out),
            "--detector",
            "energy",
            "--no-cache",
            "--no-hardware",
        ],
    )
    assert result.exit_code == 0, result.stderr
    payload = json.loads((out / "cutlist.json").read_text(encoding="utf-8"))
    assert payload["clips"]
    assert (out / "autocut.mp4").stat().st_size > 0
    assert "rendered" in result.stdout


def test_strict_aborts_before_analysis(tmp_path: Path) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    (folder / "01.mp4").write_bytes(b"")
    result = run_analyze(str(folder), "-o", str(tmp_path / "out.json"), "--strict")
    assert result.exit_code == 2
    assert "strict mode" in result.stderr


def test_strict_warnings_exits_1(tmp_path: Path) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    make_clip(folder, "01.mp4")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    (folder / "outro.mp4").write_bytes(b"")
    result = run_analyze(
        str(folder),
        "-o",
        str(tmp_path / "out.json"),
        "--detector",
        "energy",
        "--no-cache",
        "--strict-warnings",
    )
    assert result.exit_code == 1
