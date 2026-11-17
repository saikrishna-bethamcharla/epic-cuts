"""Allow ``python -m autocut`` as well as the ``autocut`` console script."""

from __future__ import annotations

from autocut.cli import main

if __name__ == "__main__":  # pragma: no cover - thin entry point
    main()
