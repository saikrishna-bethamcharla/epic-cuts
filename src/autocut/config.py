"""Validated settings, loaded from a TOML file and overridden by the CLI.

Only settings that exist in this build are modelled: ``extra="forbid"`` makes a
typo in the config file a clear input error instead of a silently ignored key.
Detection, export and render settings join this module in M2/M3.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from autocut.errors import InputError

NumberRuleName = Literal["first", "last", "regex"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class OrderingSettings(_Model):
    """How filenames are numbered and read from disk (brief 3.1)."""

    number_rule: NumberRuleName = "first"
    number_regex: str | None = None
    recursive: bool = False
    unnumbered_policy: Literal["end", "error"] = "end"

    @model_validator(mode="after")
    def _regex_required_with_rule(self) -> OrderingSettings:
        if self.number_rule == "regex" and not self.number_regex:
            raise ValueError("number_regex is required when number_rule is 'regex'")
        return self


class RunSettings(_Model):
    """Run-wide behaviour."""

    strict: bool = False
    strict_warnings: bool = False


class LogSettings(_Model):
    level: Literal["debug", "info", "warning", "error", "critical"] = "info"
    file: Path | None = None


class Config(_Model):
    ordering: OrderingSettings = Field(default_factory=OrderingSettings)
    run: RunSettings = Field(default_factory=RunSettings)
    log: LogSettings = Field(default_factory=LogSettings)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error["loc"]) or "config"
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def load_config(path: Path | None) -> Config:
    """Load a TOML config file, or return defaults when no path is given."""
    if path is None:
        return Config()

    config_path = Path(path).expanduser()
    if not config_path.exists():
        raise InputError(f"config file does not exist: {config_path}")
    if not config_path.is_file():
        raise InputError(f"config path is not a file: {config_path}")

    try:
        raw: dict[str, Any] = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise InputError(f"cannot read config file {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise InputError(f"invalid TOML in {config_path}: {exc}") from exc

    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise InputError(
            f"invalid config file {config_path}: {_format_validation_error(exc)}"
        ) from exc


def apply_overrides(config: Config, overrides: dict[str, Any]) -> Config:
    """Apply CLI overrides, dropping the ones the user did not pass.

    Values are validated by the pydantic models, so a bad value is reported as an
    input error with the offending field named.
    """
    try:
        for dotted, value in overrides.items():
            if value is None:
                continue
            section, _, field = dotted.partition(".")
            if not field:
                setattr(config, section, value)
            else:
                setattr(getattr(config, section), field, value)
    except ValidationError as exc:
        raise InputError(_format_validation_error(exc)) from exc
    return config
