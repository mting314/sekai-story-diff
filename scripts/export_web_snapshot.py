"""Publish the diff as per-scenario JSON for the sekai-viewer fork to read.

The viewer can only fetch the *current* text from the asset mirror, so it consumes the
older side from small static snapshots laid out as::

    <out>/<region>/<scenarioId>.json

matching ``src/utils/versionDiff.ts`` in the fork (``VITE_VERSION_DIFF_BASE``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


READER = "src/utils/versionDiff.ts"


def find_checkout() -> Path:
    """The sibling sekai-viewer checkout that can actually read these snapshots.

    The fork has been kept under more than one directory name, so identify it by the
    reader it must contain rather than by a hard-coded path — a stale sibling silently
    swallowing the export is the failure this avoids.
    """
    candidates = sorted(p for p in Path("..").glob("sekai-viewer*") if (p / READER).exists())
    if not candidates:
        raise SystemExit(
            f"no sibling checkout of sekai-viewer contains {READER}; pass --out "
            "explicitly to point at the fork with the version-diff branch"
        )
    if len(candidates) > 1:
        names = ", ".join(str(p) for p in candidates)
        raise SystemExit(f"ambiguous: {names} all contain {READER}; pass --out explicitly")
    return candidates[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/transitions/event_story__event_stella_2020__scenario__5.4.0.20__5.4.0.30.json")
    ap.add_argument(
        "--out",
        default="",
        help="output root; defaults to the sibling viewer checkout that has the reader",
    )
    ap.add_argument("--region", default="en")
    ap.add_argument(
        "--old-released-at",
        default="",
        help="ISO date of the old version; defaults to comparison.old_released_at",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    old_version = data["comparison"]["old_asset_version"]
    new_version = data["comparison"]["new_asset_version"]
    # Carrying the date on the comparison keeps re-exports stable: passing it only as a
    # flag means forgetting it quietly rewrites every snapshot without the field.
    released_at = args.old_released_at or data["comparison"].get("old_released_at", "")
    if not released_at:
        print("warning: no old release date — snapshots will omit oldReleasedAt")
    out = Path(args.out) if args.out else find_checkout() / "public/version-diff"
    # An explicit --out gets the same check: writing into a checkout without the reader
    # leaves untracked files that are never served, with no error.
    checkout = out.parent.parent
    if not (checkout / READER).exists():
        raise SystemExit(
            f"{checkout} has no {READER} — that checkout cannot read these snapshots. "
            "Point --out at the fork with the version-diff branch."
        )
    out_root = out / args.region
    out_root.mkdir(parents=True, exist_ok=True)

    written = 0
    for event in data["events"]:
        for episode in event["episodes"]:
            lines = [
                {
                    "talkIndex": change["talk_index_new"],
                    "old": change["old"],
                    "new": change["new"],
                    "kind": change["kind"],
                }
                for change in episode["changes"]
                if change["talk_index_new"] is not None
            ]
            if not lines:
                continue
            snapshot = {
                "scenarioId": episode["scenario_id"],
                "region": args.region,
                "oldAssetVersion": old_version,
                "newAssetVersion": new_version,
                "lines": lines,
            }
            if released_at:
                snapshot["oldReleasedAt"] = released_at
            (out_root / f"{episode['scenario_id']}.json").write_text(
                json.dumps(snapshot, ensure_ascii=False), encoding="utf-8"
            )
            written += 1

    index = {
        "region": args.region,
        "oldAssetVersion": old_version,
        "newAssetVersion": new_version,
        "scenarios": sorted(p.stem for p in out_root.glob("*.json") if p.stem != "index"),
    }
    (out_root / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"wrote {written} scenario snapshots to {out_root}")


if __name__ == "__main__":
    main()
