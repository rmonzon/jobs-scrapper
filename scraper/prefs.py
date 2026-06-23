"""User dashboard preferences: followed roles and dismissed ("not interested")
roles.

Persisted to ``data/preferences.json`` so the choices made in the dashboard
survive every rebuild and sync across browsers/machines hitting the same
server. Followed roles are stored as full job snapshots so a tracked posting
can still be shown after it disappears from the live feed ("no longer
available").

Shape on disk:

    {
      "tracked": { "<job id>": { ...job snapshot... }, ... },
      "hidden":  [ "<job id>", ... ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path

PREFS_FILENAME = "preferences.json"


def _path(data_dir: Path) -> Path:
    return data_dir / PREFS_FILENAME


def _coerce(data: dict | None) -> dict:
    """Force whatever we read/receive into the expected shape."""
    data = data or {}
    tracked = data.get("tracked")
    hidden = data.get("hidden")
    if not isinstance(tracked, dict):
        tracked = {}
    if not isinstance(hidden, list):
        hidden = []
    # de-dupe hidden ids while preserving order, and keep only strings
    seen = dict.fromkeys(str(h) for h in hidden)
    return {"tracked": tracked, "hidden": list(seen)}


def load_prefs(data_dir: Path) -> dict:
    """Return the saved preferences, or an empty set if none/unreadable."""
    path = _path(data_dir)
    if not path.exists():
        return {"tracked": {}, "hidden": []}
    try:
        return _coerce(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, OSError):
        return {"tracked": {}, "hidden": []}


def save_prefs(data_dir: Path, prefs: dict) -> dict:
    """Persist preferences atomically and return the cleaned object."""
    clean = _coerce(prefs)
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    tmp.replace(path)  # atomic: a crash mid-write never corrupts the file
    return clean
