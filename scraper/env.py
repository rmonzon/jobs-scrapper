"""Minimal .env loader (stdlib only).

Lets local runs pick up secrets like LOGO_DEV_TOKEN from a gitignored .env file
without committing them. Real environment variables (e.g. those injected by
GitHub Actions) always win — we only fill in what isn't already set.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, val)  # don't override real env (CI)
