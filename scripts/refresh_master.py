"""Refresh the EN master-DB files that supply English event and episode titles.

``events_en.json`` and ``eventStories_en.json`` live in ``data/master/`` as tracked
snapshots from ``Sekai-World/sekai-master-db-en-diff``. Without refreshing them when
a new asset version lands, any event whose ID exceeds the snapshot's ceiling gets
diffed and rendered with an empty English title and an ``untitled`` URL slug.

    python scripts/refresh_master.py
"""

from __future__ import annotations

from pathlib import Path

import requests

BASE = "https://raw.githubusercontent.com/Sekai-World/sekai-master-db-en-diff/main"
MASTER = Path("data/master")

FILES = {
    "events.json": MASTER / "events_en.json",
    "eventStories.json": MASTER / "eventStories_en.json",
}


def refresh() -> None:
    session = requests.Session()
    session.headers["User-Agent"] = "sekai-story-diff"
    MASTER.mkdir(parents=True, exist_ok=True)
    for upstream, dest in FILES.items():
        url = f"{BASE}/{upstream}"
        resp = session.get(url, timeout=60)
        resp.raise_for_status()
        parsed = resp.json()
        if not isinstance(parsed, list) or not parsed:
            raise RuntimeError(f"unexpected payload from {url}: expected non-empty JSON list")
        old_bytes = dest.read_bytes() if dest.exists() else b""
        if resp.content == old_bytes:
            print(f"{dest}: unchanged ({len(parsed)} entries)")
            continue
        dest.write_bytes(resp.content)
        print(f"{dest}: updated ({len(parsed)} entries)")


if __name__ == "__main__":
    refresh()
