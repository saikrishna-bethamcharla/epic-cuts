"""Config loading and CLI override validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from autocut.config import Config, apply_overrides, load_config
from autocut.errors import InputError


def test_defaults() -> None:
    config = load_config(None)
    assert config.ordering.number_rule == "first"
    assert config.ordering.recursive is False
    assert config.run.strict is False
    assert config.log.level == "info"


def test_loads_toml(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text(
        "[ordering]\n"
        'number_rule = "last"\n'
        "recursive = true\n"
        "\n[run]\n"
        "strict_warnings = true\n"
        "\n[log]\n"
        'level = "debug"\n',
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.ordering.number_rule == "last"
    assert config.ordering.recursive is True
    assert config.run.strict_warnings is True
    assert config.log.level == "debug"


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text('[ordering]\nnumbr_rule = "last"\n', encoding="utf-8")
    with pytest.raises(InputError, match="numbr_rule"):
        load_config(path)


def test_invalid_toml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text("[ordering\n", encoding="utf-8")
    with pytest.raises(InputError, match="invalid TOML"):
        load_config(path)


def test_missing_config_file_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="does not exist"):
        load_config(tmp_path / "nope.toml")


def test_directory_as_config_is_an_input_error(tmp_path: Path) -> None:
    with pytest.raises(InputError, match="not a file"):
        load_config(tmp_path)


def test_regex_rule_requires_a_pattern(tmp_path: Path) -> None:
    path = tmp_path / "autocut.toml"
    path.write_text('[ordering]\nnumber_rule = "regex"\n', encoding="utf-8")
    with pytest.raises(InputError, match="number_regex is required"):
        load_config(path)


def test_apply_overrides_skips_none_values() -> None:
    config = apply_overrides(Config(), {"log.level": None, "run.strict": True})
    assert config.run.strict is True
    assert config.log.level == "info"


def test_apply_overrides_rejects_bad_values() -> None:
    with pytest.raises(InputError, match="number_rule"):
        apply_overrides(Config(), {"ordering.number_rule": "middle"})


def test_apply_overrides_sets_whole_section() -> None:
    config = apply_overrides(Config(), {"log": {"level": "error"}})
    assert config.log.level == "error"
