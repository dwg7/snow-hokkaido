"""One daily run (docs/daily-ingest.md): discover and build new obs, events, state, display files, publish plan.

Processing is unattended-safe and idempotent. Upload is optional (--upload) because the Source Cooperative
login expires; without it the staging directory is prepared and the sync command is printed (a dry run).

Run by hand or from a scheduler:  just daily            (today and the two days before, no upload)
                                  just daily --upload   (after `source-coop login`)
"""
import argparse
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def run(*cmd):
    print("+", " ".join(cmd), flush=True)
    t0 = time.time()
    subprocess.run(cmd, check=True)
    print(f"  ({time.time() - t0:.0f} s)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="JST date YYYY-MM-DD (default: today in JST)")
    ap.add_argument("--lookback", type=int, default=3, help="days to check, today included")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--upload", action="store_true", help="sync to Source Cooperative (needs a valid login)")
    ap.add_argument("--no-publish", action="store_true")
    a = ap.parse_args()

    today = date.fromisoformat(a.today) if a.today else datetime.now(JST).date()
    days = [today - timedelta(days=i) for i in range(a.lookback)]  # newest first
    t_start = time.time()

    with tempfile.NamedTemporaryFile("w+", suffix=".touched", delete=False) as tf:
        touched_path = tf.name
    try:
        for d in days:
            run("just", "obs", d.isoformat(), "--workers", str(a.workers), "--touched", touched_path)
        touched = sorted({Path(l.strip()) for l in Path(touched_path).read_text().splitlines() if l.strip()})
    finally:
        Path(touched_path).unlink(missing_ok=True)

    changed_days = sorted({p.parent.name for p in touched})
    print(f"changed passes: {len(touched)}; changed days: {changed_days or 'none'}", flush=True)

    for p in touched:  # a rebuilt pass replaces its events file (same name)
        run("just", "events", str(p))

    # state is replayed from the season start (ages advance even on days without new obs); tiles only from the
    # first changed day (or today when nothing changed)
    tiles_from = min(changed_days + [today.isoformat()])
    run("just", "state", today.isoformat(), "--tiles-from", tiles_from)
    for d in changed_days:
        run("just", "view-tiles", d)
    run("just", "docs-data")

    if not a.no_publish:
        run("just", "publish", *(["--upload"] if a.upload else []))
    print(f"done in {time.time() - t_start:.0f} s", flush=True)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
