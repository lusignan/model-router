"""Module execution entrypoint for `python3 -m model_router`."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
