"""Confirm each candidate transition by actually fetching and diffing it.

``fingerprint_bundles.py`` finds where a bundle's *bytes* changed, for one byte per
probe. That is a prefilter, not an answer: a bundle can be repacked, or change in another
locale, without the English text moving — Curtain Call's bytes changed at
5.4.0.40 -> 5.5.0.1 while its text only moved at 5.5.0.20 -> 5.5.1.0.

This walks every candidate, fetches just that bundle at both versions, diffs it, and
keeps only the transitions where the text actually changed. Output is one payload per
confirmed transition, in the shape build_web_gallery.py already consumes::

    data/transitions/<bundle>__<old>__<new>.json

    python scripts/diff_transitions.py --dry-run   # cost report, fetches nothing
    python scripts/diff_transitions.py
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TRANSITIONS = Path("data/transitions.json")
OFFICIAL = Path("data/official")
OUT_DIR = Path("data/transitions")


def on_disk(bundle: str, version: str) -> bool:
    return (OFFICIAL / version / (bundle.replace("/", "__") + ".json")).exists()


def kind_of(bundle: str) -> str:
    """Which master list the fetcher must consult to recognise this bundle."""
    return "unit" if bundle.startswith("scenario/unitstory/") else "event"


def label(bundle: str) -> str:
    """Short name for progress lines. Unit arcs put the chapter last, events second."""
    parts = bundle.split("/")
    return parts[-1] if kind_of(bundle) == "unit" else parts[1]


def fetch(bundle: str, version: str) -> bool:
    """Pull one bundle at one version. Cheap now that --bundles exists.

    Runs under our own interpreter: sssekai and UnityPy are project dependencies, so
    the fetcher no longer needs the separate reverse-engineering venv it was written
    against. That venv only ever existed on one laptop, so shelling out to it made
    this step fail on any machine without it — CI included, where nothing is cached
    and so every candidate needs a fetch.
    """
    result = subprocess.run(
        [sys.executable, "scripts/fetch_official_bundles.py",
         "--kind", kind_of(bundle), "--version", version, "--bundles", bundle],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"    fetch failed {bundle} @ {version}: {result.stderr.strip()[:160]}")
    return on_disk(bundle, version)


def released_at(versions: list[dict], version: str) -> str:
    for row in versions:
        if row["version"] == version:
            return row["date"]
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report the cost, fetch nothing")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", nargs="*", default=[], help="restrict to these bundles")
    args = ap.parse_args()

    doc = json.loads(TRANSITIONS.read_text())
    versions = doc["versions"]
    jobs = [
        (bundle, t["old"], t["new"])
        for bundle, trans in sorted(doc["bundles"].items())
        for t in trans
        if not args.only or bundle in args.only
    ]
    if args.limit:
        jobs = jobs[: args.limit]

    need = {(b, v) for b, o, n in jobs for v in (o, n) if not on_disk(b, v)}
    print(f"{len(jobs)} candidate transitions over {len({b for b, _, _ in jobs})} bundles")
    print(f"  bundle-versions already cached: {len({(b, v) for b, o, n in jobs for v in (o, n)}) - len(need)}")
    print(f"  to fetch: {len(need)}")
    if args.dry_run:
        print("\n  dry run — nothing fetched. Re-run without --dry-run to confirm these.")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    confirmed = spurious = failed = 0
    for i, (bundle, old, new) in enumerate(jobs, 1):
        name = label(bundle)
        for version in (old, new):
            if not on_disk(bundle, version) and not fetch(bundle, version):
                print(f"  [{i}/{len(jobs)}] {name} {old}->{new}: FETCH FAILED")
                failed += 1
                break
        else:
            out = OUT_DIR / f"{bundle.replace('/', '__')}__{old}__{new}.json"
            result = subprocess.run(
                [sys.executable, "scripts/diff_versions.py",
                 "--old", old, "--new", new, "--bundles", bundle,
                 "--old-released-at", released_at(versions, old),
                 "--new-released-at", released_at(versions, new),
                 "--out", str(out)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                print(f"  [{i}/{len(jobs)}] {name} {old}->{new}: DIFF FAILED "
                      f"{result.stderr.strip()[:160]}")
                failed += 1
                continue
            payload = json.loads(out.read_text())
            changed = payload["totals"]["changed_lines"]
            if not changed:
                # the ETag moved but the English text did not
                out.unlink()
                spurious += 1
                print(f"  [{i}/{len(jobs)}] {name} {old}->{new}: no text change (bytes only)")
            else:
                confirmed += 1
                kinds = payload["totals"]["by_kind"]
                print(f"  [{i}/{len(jobs)}] {name} {old}->{new}: {changed} lines {kinds}")

    print(f"\n{confirmed} confirmed, {spurious} bytes-only, {failed} failed")
    print(f"payloads in {OUT_DIR}/")
    print("next: scripts/build_web_gallery.py --changes 'data/transitions/*.json' "
          "'data/official_changes*.json'")

    # A failed candidate is a transition we know moved and cannot account for. Exiting 0
    # here made that invisible: CI counts payload files to decide whether to render, so a
    # run where every diff failed looks exactly like a run where nothing changed, and the
    # site keeps under-reporting with a green tick. The retention window is ~11 months,
    # so a transition not diffed while it is live is lost for good — fail loudly instead.
    if failed:
        raise SystemExit(f"{failed} candidate transition(s) could not be confirmed")


if __name__ == "__main__":
    main()
