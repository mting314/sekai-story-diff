"""Has a new EN asset version shipped since we last looked?

There is nothing to subscribe to. Colorful Palette publish no feed, and their public
version endpoint returns only the assetbundle host handshake — no ``assetVersion``.
Sekai-World get it by running an authenticated game client on a timer and committing
the result, so the cheapest honest source is the file that client produces.

That makes us structurally downstream: our latency is theirs plus ours. Their bot
commits mostly at 07:30 and 19:00 UTC, so polling shortly after catches most releases
quickly.

Costs nothing to ask: the source supports conditional requests, so a run where nothing
has changed is a 304 with an empty body.

    python scripts/check_new_version.py            # human-readable
    python scripts/check_new_version.py --github   # also writes to $GITHUB_OUTPUT
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests

SOURCE = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main/versions.json"
ETAG_CACHE = Path("data/versions_etag.json")
INDEX = Path("data/versions_en.json")


def known_versions(path: Path) -> set[str]:
    if not path.exists():
        return set()
    return {row["version"] for row in json.loads(path.read_text())}


def fetch(url: str, etag: str | None) -> tuple[int, dict | None, str | None]:
    headers = {"User-Agent": "sekai-story-diff"}
    if etag:
        headers["If-None-Match"] = etag
    resp = requests.get(url, headers=headers, timeout=60)
    if resp.status_code == 304:
        return 304, None, etag
    resp.raise_for_status()
    return resp.status_code, resp.json(), resp.headers.get("etag")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--github", action="store_true", help="write key=value to $GITHUB_OUTPUT")
    ap.add_argument("--index", default=str(INDEX))
    args = ap.parse_args()

    cache = json.loads(ETAG_CACHE.read_text()) if ETAG_CACHE.exists() else {}
    status, payload, etag = fetch(SOURCE, cache.get("etag"))

    known = known_versions(Path(args.index))
    if status == 304:
        version = digest = ""
        is_new = False
        print("304 not modified — nothing to do")
    else:
        version = payload.get("assetVersion", "")
        digest = payload.get("assetHash", "")
        is_new = bool(version) and version not in known
        print(f"upstream assetVersion {version} ({digest})")
        print(f"  app {payload.get('appVersion')} / {payload.get('appHash')}")
        print(f"  known locally: {len(known)} versions")
        print(f"  NEW: {is_new}")

    # Only persist the etag when the answer was acted on. Storing it after seeing a new
    # version we have not indexed yet would make the next run return 304 and skip it.
    if etag and not is_new:
        ETAG_CACHE.parent.mkdir(parents=True, exist_ok=True)
        ETAG_CACHE.write_text(json.dumps({"etag": etag}, indent=1))

    out = os.environ.get("GITHUB_OUTPUT")
    if args.github and out:
        with open(out, "a", encoding="utf-8") as handle:
            handle.write(f"new={'true' if is_new else 'false'}\n")
            handle.write(f"version={version}\n")
            handle.write(f"hash={digest}\n")

    raise SystemExit(0 if not is_new else 10)  # 10 = new version, for scripting


if __name__ == "__main__":
    main()
