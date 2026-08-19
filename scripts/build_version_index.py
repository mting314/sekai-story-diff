"""Index every EN asset version the game CDN still serves.

The CDN is addressed by ``(assetVersion, assetHash)`` and keeps roughly ten months of
releases, but nothing in the game exposes the list. It is recoverable from the commit
history of ``versions.json`` in ``Sekai-World/sekai-master-db-en-diff``: each commit that
touches that file records the pair current at that moment.

Until now no code did this — the two hashes the pipeline used were pasted into the README
by hand, which is why adding a version pair was a manual research step. Output::

    data/versions_en.json  [{"date": "2026-06-30", "version": "5.4.0.20", "hash": "..."}]

sorted oldest first. Several commits repeat an assetVersion (a release touching other
fields), so the list is deduped on the pair.

    python scripts/build_version_index.py
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import requests

REPO = "Sekai-World/sekai-master-db-en-diff"
FILE = "versions.json"
# The commit list needs the API, but each blob can come from raw.githubusercontent, which
# is not rate limited — fetching 70 blobs through the API would exhaust the unauthenticated
# hourly allowance in one run.
API = f"https://api.github.com/repos/{REPO}/commits"
RAW = f"https://raw.githubusercontent.com/{REPO}"

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"
# The commit-list endpoint is rate limited to 60/hour unauthenticated, which a single
# backfill can exhaust. Any token raises it to 5,000; Actions provides one for free.
_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
if _token:
    _session.headers["Authorization"] = f"Bearer {_token}"


def commits(pages: int) -> list[tuple[str, str]]:
    """(sha, iso date) for every commit touching versions.json, newest first."""
    out: list[tuple[str, str]] = []
    for page in range(1, pages + 1):
        resp = _session.get(
            API, params={"path": FILE, "per_page": 100, "page": page}, timeout=60
        )
        if resp.status_code != 200:
            raise SystemExit(f"github api {resp.status_code}: {resp.text[:200]}")
        batch = resp.json()
        if not batch:
            break
        out += [(c["sha"], c["commit"]["committer"]["date"]) for c in batch]
        if len(batch) < 100:
            break
    return out


def version_at(sha: str) -> tuple[str, str] | None:
    resp = _session.get(f"{RAW}/{sha}/{FILE}", timeout=60)
    if resp.status_code != 200:
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    row = data[0] if isinstance(data, list) else data
    version, digest = row.get("assetVersion"), row.get("assetHash")
    return (version, digest) if version and digest else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/versions_en.json")
    ap.add_argument("--pages", type=int, default=5, help="pages of 100 commits to walk")
    ap.add_argument(
        "--append",
        nargs=3,
        metavar=("VERSION", "HASH", "DATE"),
        help="add one known release without touching the API — the normal daily path, "
             "since the poller already has these three values",
    )
    args = ap.parse_args()

    if args.append:
        version, digest, date = args.append
        out = Path(args.out)
        rows = json.loads(out.read_text()) if out.exists() else []
        if any(r["version"] == version for r in rows):
            print(f"{version} already indexed")
            return
        rows.append({"date": date, "hash": digest, "version": version})
        rows.sort(key=lambda r: r["date"])
        out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
        print(f"appended {version} ({date}); {len(rows)} versions indexed")
        return

    history = commits(args.pages)
    print(f"{len(history)} commits touch {FILE}")

    seen: set[tuple[str, str]] = set()
    rows: list[dict] = []
    for sha, date in history:
        pair = version_at(sha)
        if not pair or pair in seen:
            continue
        seen.add(pair)
        rows.append({"date": date[:10], "hash": pair[1], "version": pair[0]})
    rows.sort(key=lambda r: r["date"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"wrote {out}: {len(rows)} distinct versions, {rows[0]['date']} .. {rows[-1]['date']}")


def load(path: str = "data/versions_en.json") -> list[dict]:
    """The index, oldest first. Other scripts use this to resolve a version to its hash."""
    return json.loads(Path(path).read_text())


def resolve(version: str, path: str = "data/versions_en.json") -> str:
    """assetVersion -> assetHash."""
    for row in load(path):
        if row["version"] == version:
            return row["hash"]
    raise SystemExit(f"unknown assetVersion {version}; run scripts/build_version_index.py")


if __name__ == "__main__":
    main()
