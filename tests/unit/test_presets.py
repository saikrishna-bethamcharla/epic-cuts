"""Named presets: registry, lookup and config-file precedence."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.config import Config, load_config
from autocut.errors import InputError
from autocut.presets import (
    PRESETS,
    describe_presets,
    get_preset,
    preset_names,
    preset_settings,
)

EXPECTED_PROFILES = ("podcast", "tutorial", "vlog", "aggressive", "gentle")


def test_registry_holds_the_documented_profiles() -> None:
    assert preset_names() == EXPECTED_PROFILES
    for key, preset in PRESETS.items():
        assert key == preset.name


def test_describe_presets_matches_the_registry() -> None:
    described = describe_presets()
    assert [name for name, _ in described] == list(preset_names())
    assert all(summary for _, summary in described)


@pytest.mark.parametrize("name", EXPECTED_PROFILES)
def test_every_preset_validates_as_a_partial_config(name: str) -> None:
    config = Config.model_validate(preset_settings(name))
    assert config.analysis.min_silence >= 0
    assert config.render.crf >= 0
    assert 0 <= config.render.crossfade_ms <= 5000


def test_preset_settings_are_a_copy() -> None:
    settings = preset_settings("podcast")
    settings["analysis"]["min_silence"] = 99.0
    assert preset_settings("podcast")["analysis"]["min_silence"] != 99.0


def test_unknown_preset_suggests_the_closest_name() -> None:
    with pytest.raises(InputError, match="did you mean 'podcast'"):
        get_preset("podcas")


def test_unknown_preset_lists_every_name() -> None:
    with pytest.raises(InputError, match="aggressive"):
        get_preset("cinematic")


def test_profile_in_the_config_file_applies_the_preset(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text('profile = "aggressive"\n', encoding="utf-8")
    config = load_config(path)
    assert config.profile == "aggressive"
    assert config.analysis.min_silence == pytest.approx(0.25)
    assert config.render.crf == 22


def test_config_file_values_beat_the_preset(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text(
        'profile = "aggressive"\n\n[analysis]\nmin_silence = 0.75\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.analysis.min_silence == pytest.approx(0.75)
    assert config.analysis.pad_before == pytest.approx(0.05)


def test_cli_profile_beats_the_file_profile(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text('profile = "gentle"\n', encoding="utf-8")
    config = load_config(path, profile="aggressive")
    assert config.profile == "aggressive"
    assert config.analysis.min_silence == pytest.approx(0.25)


def test_profile_without_a_config_file(tmp_path: Path) -> None:
    config = load_config(None, profile="Tutorial")
    assert config.profile == "tutorial"
    assert config.analysis.min_silence == pytest.approx(0.80)


def test_no_profile_leaves_the_defaults() -> None:
    assert load_config(None).profile is None


def test_unknown_profile_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="unknown profile"):
        load_config(None, profile="cinematic")


def test_profile_key_does_not_leak_into_the_models() -> None:
    config = load_config(None, profile="vlog")
    dumped = config.model_dump()
    assert dumped["profile"] == "vlog"
    assert "profile" not in dumped["analysis"]
