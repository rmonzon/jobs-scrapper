"""Generate the dashboard's data from saved state + discovery feed.

The visual design mirrors the "Job Tracker Dark" Claude Design mockup (DM Sans /
DM Mono, oklch dark palette, live pill, stat cards, job table with NEW badges).
All data is real: jobs come from the saved state snapshots, "new" status from the
discovery-events feed, and logos from logo.dev (config token), with a colored
initial tile as fallback.

The page itself is static (dashboard/index.html, app.js, styles.css). Each run
writes dashboard/data.js, which sets ``window.__JT_DATA`` (jobs, logo.dev token,
domains, filters, prefs). It's a script rather than JSON so the page also works
by double-clicking index.html (file://), where fetch() of a local file is
blocked. Web fonts load from Google when online and fall back to system fonts.

Regenerated at the end of every run; also runnable standalone:

    python3 -m scraper.dashboard
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from scraper import prefs as prefs_store
from scraper import store
from scraper.filters import work_arrangement


def _slug(company: str) -> str:
    return company.lower().replace("/", "-").replace(" ", "-")


def _relative(ts: str, today: date) -> str:
    """Best-effort 'how long ago' from a provider timestamp (ISO string or epoch
    seconds/millis). Returns '' when it can't be parsed."""
    if not ts:
        return ""
    s = str(ts).strip()
    try:
        if s.isdigit():
            v = int(s)
            if v > 1_000_000_000_000:  # epoch millis
                v //= 1000
            d = datetime.fromtimestamp(v, timezone.utc).date()
        else:
            d = datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except (ValueError, OSError, OverflowError):
        return ""
    days = (today - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "1d ago"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def collect(data_dir: Path, config: dict) -> dict:
    """Pull together everything the dashboard needs from disk + config."""
    today = date.today()
    today_str = today.isoformat()

    meta = {}
    for c in config.get("companies", []):
        meta[_slug(c["company"])] = {"name": c["company"],
                                     "domain": c.get("domain", "")}

    # Jobs discovered on today's run → drives "New Today" + the NEW badge.
    # (Seed runs record no events, so a first run never floods the page.)
    events_raw = store.load_events(data_dir)
    new_ids_today = {e["id"] for e in events_raw if e.get("date") == today_str}

    state_dir = data_dir / store.STATE_DIRNAME
    companies = []
    jobs = []
    remote_count = 0
    if state_dir.exists():
        for path in sorted(state_dir.glob("*.json")):
            info = meta.get(path.stem, {"name": path.stem.replace("-", " ").title(),
                                        "domain": ""})
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            roles = list(snapshot.values())
            companies.append({"company": info["name"], "domain": info["domain"],
                              "count": len(roles)})
            for r in roles:
                loc = r.get("location", "")
                # Older snapshots predate work_type; classify from location.
                work_type = r.get("work_type") or work_arrangement(loc)
                if work_type == "remote":
                    remote_count += 1
                jobs.append({
                    "id": r.get("id", ""),
                    "company": info["name"],
                    "domain": info["domain"],
                    "title": r.get("title", ""),
                    "location": loc,
                    "work_type": work_type,
                    "url": r.get("url", ""),
                    "remote": work_type == "remote",
                    "isNew": r.get("id", "") in new_ids_today,
                    "updated": _relative(r.get("updated_at", ""), today),
                })

    # New roles first, then alphabetical by company + title.
    jobs.sort(key=lambda j: (not j["isNew"], j["company"].lower(), j["title"].lower()))

    # Machine-readable UTC instant; the browser formats it in the viewer's own
    # timezone. (Pre-formatting here would bake in the build machine's zone —
    # UTC on the CI runner — which is wrong for everyone reading it elsewhere.)
    status = store.load_run_status(data_dir) or {}

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "update_ok": status.get("ok", True),
        "update_errors": status.get("errors", []),
        "logo_token": os.environ.get("LOGO_DEV_TOKEN")
        or config.get("logo_dev", {}).get("publishable_token", ""),
        "companies": sorted(companies, key=lambda c: c["company"]),
        "jobs": jobs,
        "total_jobs": len(jobs),
        "new_count": len(new_ids_today),
        "remote_count": remote_count,
        # Filters the scraper applied; the page shows the keywords as its
        # default keyword list.
        "filters": config.get("filters", {}),
        # Followed / dismissed roles, embedded so the page renders correctly on
        # first paint (over HTTP the dashboard then reconciles via /api/prefs).
        "prefs": prefs_store.load_prefs(data_dir),
    }


def _load_config(config_path: Path) -> dict:
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def build_dashboard(data_dir: Path, out_dir: Path,
                    config_path: Path | None = None) -> Path:
    """Write ``out_dir/data.js`` for the static dashboard and return its path."""
    config = _load_config(config_path) if config_path else {}
    data = collect(data_dir, config)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "data.js"
    payload = json.dumps(data, ensure_ascii=False)
    tmp = out.with_suffix(".js.tmp")
    tmp.write_text(f"window.__JT_DATA = {payload};\n", encoding="utf-8")
    tmp.replace(out)  # atomic: the server never serves a half-written file
    return out


if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    from scraper.env import load_env
    load_env(root / ".env")
    out = build_dashboard(root / "data", root / "dashboard", root / "config.json")
    print(f"dashboard data written to {out}")
