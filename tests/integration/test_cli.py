"""End-to-end CLI behaviour with the documented exit codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from autocut import __version__
from autocut.cli import app
from tests.conftest import ClipBuilder, make_clips

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert f"autocut {__version__}" in result.stdout


def test_order_prints_the_table_in_number_order(tmp_path: Path) -> None:
    make_clips(tmp_path, ["10.mp4", "2.mp4", "1.mp4"])
    result = runner.invoke(app, ["order", str(tmp_path)])
    assert result.exit_code == 0
    assert result.stdout.index("1.mp4") < result.stdout.index("10.mp4")


def test_order_json_output(tmp_path: Path) -> None:
    make_clips(tmp_path, ["2.mp4", "1.mp4"])
    target = tmp_path / "reports" / "ordering.json"
    result = runner.invoke(app, ["order", str(tmp_path), "--json-out", str(target)])
    assert result.exit_code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert [clip["filename"] for clip in payload["clips"]] == ["1.mp4", "2.mp4"]


def test_order_strict_aborts_with_exit_2(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "intro.mp4"])
    result = runner.invoke(app, ["order", str(tmp_path), "--strict"])
    assert result.exit_code == 2
    assert "error: strict mode:" in result.stderr


def test_order_strict_warnings_exits_1(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "intro.mp4"])
    result = runner.invoke(app, ["order", str(tmp_path), "--strict-warnings"])
    assert result.exit_code == 1
    assert "no number" in result.stdout


def test_order_without_strict_warnings_exits_0(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4", "intro.mp4"])
    assert runner.invoke(app, ["order", str(tmp_path)]).exit_code == 0


def test_order_missing_path_is_exit_2(tmp_path: Path) -> None:
    result = runner.invoke(app, ["order", str(tmp_path / "nope")])
    assert result.exit_code == 2
    assert "does not exist" in result.stderr


def test_order_rejects_bad_number_rule(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    result = runner.invoke(app, ["order", str(tmp_path), "--number-rule", "middle"])
    assert result.exit_code == 2
    assert "number_rule" in result.stderr


def test_order_honours_toml_config(tmp_path: Path) -> None:
    make_clips(tmp_path, ["S01E02.mp4", "S01E01.mp4"])
    config = tmp_path / "autocut.toml"
    config.write_text('[ordering]\nnumber_rule = "last"\n', encoding="utf-8")
    result = runner.invoke(app, ["order", str(tmp_path), "--config", str(config)])
    assert result.exit_code == 0
    assert result.stdout.index("S01E01") < result.stdout.index("S01E02")


def test_run_dry_run_writes_both_reports(tmp_path: Path) -> None:
    make_clips(tmp_path, ["2.mp4", "1.mp4"])
    out = tmp_path / "out"
    result = runner.invoke(app, ["run", str(tmp_path), "-o", str(out), "--dry-run"])
    assert result.exit_code == 0
    assert (out / "ordering_report.txt").exists()
    assert (out / "ordering.json").exists()
    assert "dry run: stopping before analysis" in result.stdout


def test_run_without_dry_run_writes_the_cutlist_and_renders(
    tmp_path: Path, tone_clip: ClipBuilder
) -> None:
    tone_clip("1.mp4", seconds=1.0)
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run",
            str(tmp_path),
            "-o",
            str(out),
            "--detector",
            "energy",
            "--no-cache",
            "--no-hardware",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert (out / "cutlist.json").exists()
    assert (out / "autocut.mp4").stat().st_size > 0


def test_export_rejects_an_unknown_format(tmp_path: Path) -> None:
    cutlist = tmp_path / "cutlist.json"
    cutlist.write_text("{}", encoding="utf-8")
    export = runner.invoke(app, ["export", str(cutlist), "--format", "aaf"])
    assert export.exit_code == 2
    assert "unknown export format" in export.stderr


def test_doctor_reports_a_usable_environment(ffmpeg_available: bool) -> None:
    result = runner.invoke(app, ["doctor"])
    if ffmpeg_available:
        assert result.exit_code == 0
        assert "status: ready" in result.stdout
        assert "hardware encoders:" in result.stdout
    else:  # pragma: no cover - CI always installs ffmpeg
        assert result.exit_code == 3
        assert "NOT READY" in result.stdout


def test_presets_lists_every_builtin_profile() -> None:
    result = runner.invoke(app, ["presets"])
    assert result.exit_code == 0
    for name in ("podcast", "tutorial", "vlog", "aggressive", "gentle"):
        assert name in result.stdout
    assert "--profile" in result.stdout


def test_unknown_profile_is_exit_2(tmp_path: Path) -> None:
    make_clips(tmp_path, ["1.mp4"])
    result = runner.invoke(app, ["order", str(tmp_path), "--profile", "cinematic"])
    assert result.exit_code == 2
    assert "unknown profile" in result.stderr


def test_order_probes_real_media(tmp_path: Path, tone_clip: ClipBuilder) -> None:
    tone_clip("2.mp4", seconds=1.0)
    tone_clip("1.mp4", seconds=1.0)
    target = tmp_path / "ordering.json"
    result = runner.invoke(app, ["order", str(tmp_path), "--json-out", str(target)])
    assert result.exit_code == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert [clip["status"] for clip in payload["clips"]] == ["ok", "ok"]
    assert payload["clips"][0]["resolution"] == "320x240"
    assert payload["clips"][0]["duration"] == pytest.approx(1.0, abs=0.2)
    assert payload["clips"][0]["audio_streams"] == 1
