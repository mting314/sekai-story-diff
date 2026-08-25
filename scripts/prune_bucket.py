"""Delete objects in the asset bucket that no longer appear in the payload.

Every reclassification, re-render or dropped event leaves media behind. The objects are
immutable and content-addressed, so nothing breaks and the bill is about $0.001/month —
but the set only grows, and there is otherwise no way to tell a live sprite from a dead
one without rebuilding the payload.

This walks the same references ``verify_payload.py`` checks, in the opposite direction:
that script asks "is everything the payload needs present?", this one asks "is everything
present still needed?".

    uv run python scripts/prune_bucket.py             # report only, deletes nothing
    uv run python scripts/prune_bucket.py --delete    # actually remove them

Deletion is guarded. It refuses to run unless every object the payload references is
already in the bucket: if a reference is missing, either the walk is wrong or the bucket
is mid-upload, and in neither case should anything be removed. The bucket also has a
7-day soft-delete retention, so a mistake is recoverable — check before relying on it::

    gcloud storage buckets describe gs://sekai-story-diff-assets \\
      --format='value(soft_delete_policy.retentionDurationSeconds)'
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BUCKET = "gs://sekai-story-diff-assets"
# Only the classes this pipeline generates. unit/ holds six band logos copied from the
# viewer as a source asset — they are tracked in git, not produced here, and pruning the
# one unreferenced logo would save 50 KB while risking a needless re-upload later.
MANAGED = ("sprites/", "bg/", "event/", "logo/")


def referenced(payload: dict) -> set[str]:
    """Every object name the site can ask for."""
    out = {
        "sprites/" + entry["file"]
        for entry in payload.get("sprites", {}).values()
        if entry.get("file")
    }
    out |= {
        "bg/" + frame["bg"] + ".webp"
        for event in payload.get("events", [])
        for transition in event.get("transitions", [])
        for episode in transition.get("episodes", [])
        for frame in episode.get("frames", [])
        if frame.get("bg") and not frame.get("cover")
    }
    # banner / logo / unitLogo already carry their directory
    out |= {
        path
        for event in payload.get("events", []) + payload.get("pending", [])
        for key in ("banner", "logo", "unitLogo")
        if (path := event.get(key))
    }
    return out


def bucket_objects() -> set[str]:
    result = subprocess.run(
        ["gcloud", "storage", "ls", "--recursive", f"{BUCKET}/**"],
        capture_output=True, text=True, check=True,
    )
    prefix = BUCKET + "/"
    return {
        line[len(prefix):]
        for line in result.stdout.split()
        if line.startswith(prefix) and not line.endswith("/")
    }


def prune_local(root: Path, want: set[str], delete: bool) -> None:
    """Same reference set, applied to the local staging copy of the bucket."""
    have = {
        str(p.relative_to(root))
        for d in MANAGED
        for p in (root / d.rstrip("/")).glob("*")
        if p.is_file()
    }
    orphans = sorted(have - want)
    print(f"{root}: {len(have)} managed file(s), {len(orphans)} orphaned")
    by_dir: dict[str, int] = {}
    for name in orphans:
        by_dir[name.split("/")[0]] = by_dir.get(name.split("/")[0], 0) + 1
    for directory, count in sorted(by_dir.items()):
        print(f"    {directory:<10} {count}")
    missing = sorted(w for w in want if w.startswith(MANAGED) and not (root / w).exists())
    if missing:
        raise SystemExit(
            f"\nrefusing: {len(missing)} referenced file(s) are not in {root} — pull the "
            f"media first (scripts/pull_media.sh)\n  " + "\n  ".join(missing[:5])
        )
    if not orphans:
        print("nothing to prune")
        return
    if not delete:
        print(f"\nreport only. Re-run with --delete to remove {len(orphans)} file(s).")
        return
    freed = 0
    for name in orphans:
        path = root / name
        freed += path.stat().st_size
        path.unlink()
    print(f"deleted {len(orphans)} file(s), freed {freed / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", default="web/src/data.json")
    ap.add_argument("--delete", action="store_true", help="actually remove the orphans")
    ap.add_argument("--limit", type=int, default=0, help="cap deletions (debug)")
    ap.add_argument(
        "--local",
        nargs="?",
        const="web/public",
        default="",
        help="prune the local staging mirror instead of the bucket. Worth doing after a "
             "bucket prune: web/public is what gets rsynced up, so leaving the orphans "
             "there means the next upload from this machine puts them all back",
    )
    args = ap.parse_args()

    payload = json.loads(Path(args.payload).read_text())
    want = referenced(payload)
    # A payload that failed to build would reference almost nothing and make every
    # object look like an orphan. Refuse rather than empty the bucket.
    if len(payload.get("events", [])) < 1 or len(want) < 100:
        raise SystemExit(
            f"{args.payload} references only {len(want)} object(s) across "
            f"{len(payload.get('events', []))} event(s) — that is not a real payload"
        )

    if args.local:
        return prune_local(Path(args.local), want, args.delete)

    have = bucket_objects()
    managed = {o for o in have if o.startswith(MANAGED)}
    unmanaged = have - managed
    missing = sorted(want - have)
    orphans = sorted(managed - want)

    print(f"payload references : {len(want):>6}")
    print(f"bucket holds       : {len(have):>6}  ({len(managed)} managed, "
          f"{len(unmanaged)} outside {', '.join(MANAGED)})")
    print(f"orphaned           : {len(orphans):>6}")
    by_dir: dict[str, int] = {}
    for name in orphans:
        by_dir[name.split("/")[0]] = by_dir.get(name.split("/")[0], 0) + 1
    for directory, count in sorted(by_dir.items()):
        print(f"    {directory:<10} {count}")

    if missing:
        raise SystemExit(
            f"\nrefusing to delete: {len(missing)} referenced object(s) are NOT in the "
            f"bucket, so the payload and the bucket disagree.\n  "
            + "\n  ".join(missing[:10])
        )

    if not orphans:
        print("\nnothing to prune")
        return
    if not args.delete:
        print("\n  ".join(["\nwould delete (first 10):"] + orphans[:10]))
        print(f"\nreport only. Re-run with --delete to remove {len(orphans)} object(s).")
        return

    targets = orphans[: args.limit] if args.limit else orphans
    print(f"\ndeleting {len(targets)} object(s)…")
    # one call per batch; the arg list is long but well inside the limit at this size
    for start in range(0, len(targets), 200):
        batch = targets[start:start + 200]
        subprocess.run(
            ["gcloud", "storage", "rm", "--quiet", *[f"{BUCKET}/{n}" for n in batch]],
            check=True,
        )
        print(f"  {min(start + 200, len(targets))}/{len(targets)}")
    print("done")


if __name__ == "__main__":
    main()
