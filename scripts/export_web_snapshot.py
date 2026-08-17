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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument(
        "--out",
        default="../sekai-viewer/public/version-diff",
        help="output root; the viewer serves this at /version-diff",
    )
    ap.add_argument("--region", default="en")
    ap.add_argument("--old-released-at", default="", help="ISO date of the old version")
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    old_version = data["comparison"]["old_asset_version"]
    new_version = data["comparison"]["new_asset_version"]
    out_root = Path(args.out) / args.region
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
            if args.old_released_at:
                snapshot["oldReleasedAt"] = args.old_released_at
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
