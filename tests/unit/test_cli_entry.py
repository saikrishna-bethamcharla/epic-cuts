"""The console-script entry point has to support frozen processes."""

from __future__ import annotations

import multiprocessing

import pytest

import autocut.cli as cli_module


def test_main_enables_frozen_multiprocessing_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    monkeypatch.setattr(
        multiprocessing, "freeze_support", lambda: calls.append("freeze_support")
    )

    def fake_app(**kwargs: object) -> None:
        calls.append("app")

    monkeypatch.setattr(cli_module, "app", fake_app)

    cli_module.main()

    assert calls == ["freeze_support", "app"]
