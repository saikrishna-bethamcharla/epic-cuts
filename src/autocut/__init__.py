"""AutoCut: order numbered clips, cut silence, export editor timelines.

The package is split into layers that only depend downwards:
media -> analysis -> planning -> export -> interface (CLI, later service/UI).
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
