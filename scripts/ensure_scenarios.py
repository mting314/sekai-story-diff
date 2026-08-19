"""Fetch any scenario bundles the payload build needs but does not have.

``build_web_gallery.py`` reads the decrypted scenario for each event at its *new*
version, to work out who is on stage and what the scene looks like. That cache is far
too large to track (543 MB), so on a fresh checkout it is simply absent and the build
dies on the first missing file.

Only the versions actually referenced by the diff payloads are needed — 62 files, about
64 MB — not the whole cache. This works out which those are and fetches the missing
ones through the existing downloader.

    python scripts/ensure_scenarios.py            # fetch what is missing
    python scripts/ensure_scenarios.py --dry-run  # just say what is missing
"""

from __future__ import annotations

import argparse
import glob
import json
import subprocess
import sys
from pathlib import Path

OFFICIAL = Path("data/official")


def required(patterns: list[str]) -> set[tuple[str, str]]:
    """(assetVersion, bundle) pairs the payload build will open."""
    out: set[tuple[str, str]] = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            payload = json.loads(Path(path).read_text())
            version = payload["comparison"]["new_asset_version"]
            for event in payload["events"]:
                out.add((version, event["bundle"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--changes",
        nargs="+",
        default=["data/official_changes.json", "data/official_changes_*.json",
                 "data/transitions/*.json"],
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    wanted = required(args.changes)
    missing = [
        (version, bundle)
        for version, bundle in sorted(wanted)
        if not (OFFICIAL / version / (bundle.replace("/", "__") + ".json")).exists()
    ]
    print(f"{len(wanted)} scenario files referenced, {len(missing)} missing")
    if args.dry_run or not missing:
        for version, bundle in missing[:10]:
            print(f"  missing {version} {bundle}")
        return

    # group by version so each one costs a single handshake
    by_version: dict[str, list[str]] = {}
    for version, bundle in missing:
        by_version.setdefault(version, []).append(bundle)

    for version, bundles in sorted(by_version.items()):
        print(f"  fetching {len(bundles)} bundle(s) at {version}")
        result = subprocess.run(
            [sys.executable, "scripts/fetch_official_bundles.py",
             "--version", version, "--bundles", *bundles],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SystemExit(f"fetch failed at {version}: {result.stderr.strip()[:300]}")

    still = [
        (v, b) for v, b in missing
        if not (OFFICIAL / v / (b.replace("/", "__") + ".json")).exists()
    ]
    if still:
        raise SystemExit(f"{len(still)} scenario files still missing after fetching, e.g. {still[:3]}")
    print("  all present")


if __name__ == "__main__":
    main()
