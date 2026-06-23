"""Notification step.

Always: print a summary to stdout and write a dated Markdown digest under
``data/digests/``. Optionally: email the digest if SMTP env vars are set, so the
nightly cron run can land in your inbox.

To enable email (e.g. Gmail), set these in the cron environment:
    JOBS_SMTP_HOST=smtp.gmail.com
    JOBS_SMTP_PORT=587
    JOBS_SMTP_USER=you@gmail.com
    JOBS_SMTP_PASS=<a Google "App Password", not your login password>
    JOBS_SMTP_TO=you@gmail.com
"""

from __future__ import annotations

import os
import smtplib
from datetime import date
from email.message import EmailMessage
from pathlib import Path


def build_digest(results: list[dict], run_date: str) -> str:
    """results: list of {company, new: [...], removed: [...], error: str|None}."""
    total_new = sum(len(r["new"]) for r in results)
    lines = [f"# New job postings — {run_date}", ""]

    if total_new == 0:
        lines.append("_No new postings since the last run._")
    else:
        lines.append(f"**{total_new} new posting(s)** across "
                     f"{sum(1 for r in results if r['new'])} compan(ies).")
    lines.append("")

    for r in sorted(results, key=lambda r: r["company"].lower()):
        if r.get("error"):
            lines.append(f"## {r['company']}")
            lines.append(f"> ⚠️ fetch failed: {r['error']}")
            lines.append("")
            continue
        if not r["new"]:
            continue
        lines.append(f"## {r['company']} — {len(r['new'])} new")
        for j in r["new"]:
            loc = f" — _{j['location']}_" if j["location"] else ""
            lines.append(f"- [{j['title']}]({j['url']}){loc}")
        lines.append("")

    # A quiet footer so failures are never silently swallowed.
    errors = [r for r in results if r.get("error")]
    seeded = [r for r in results if r.get("seeded")]
    if seeded:
        lines.append(f"_Seeded (first run, no diff): "
                     f"{', '.join(r['company'] for r in seeded)}._")
    if errors:
        lines.append(f"_Errors: {len(errors)}._")
    return "\n".join(lines).rstrip() + "\n"


def write_digest(data_dir: Path, digest: str, run_date: str) -> Path:
    out_dir = data_dir / "digests"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{run_date}.md"
    path.write_text(digest, encoding="utf-8")
    return path


def maybe_email(digest: str, run_date: str) -> bool:
    """Send the digest via SMTP if fully configured. Returns True if sent."""
    host = os.environ.get("JOBS_SMTP_HOST")
    user = os.environ.get("JOBS_SMTP_USER")
    password = os.environ.get("JOBS_SMTP_PASS")
    to = os.environ.get("JOBS_SMTP_TO") or user
    if not (host and user and password and to):
        return False

    msg = EmailMessage()
    msg["Subject"] = f"Job tracker — {run_date}"
    msg["From"] = user
    msg["To"] = to
    msg.set_content(digest)

    port = int(os.environ.get("JOBS_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        s.starttls()
        s.login(user, password)
        s.send_message(msg)
    return True


def notify(data_dir: Path, results: list[dict]) -> Path:
    run_date = date.today().isoformat()
    digest = build_digest(results, run_date)
    path = write_digest(data_dir, digest, run_date)

    total_new = sum(len(r["new"]) for r in results)
    print(digest)
    print(f"[notify] digest written to {path}")
    try:
        if maybe_email(digest, run_date):
            print("[notify] emailed digest")
    except Exception as exc:  # email is best-effort; never fail the run over it
        print(f"[notify] email failed: {exc}")
    print(f"[notify] {total_new} new posting(s) this run")
    return path
