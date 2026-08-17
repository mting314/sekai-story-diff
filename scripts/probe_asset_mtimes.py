"""HEAD every EN scenario asset and record its ``Last-Modified`` date.

The CDN mirror re-uploads a scenario asset when the game ships a new version of it,
so the modified date is a direct, source-of-truth signal for *which* episodes were
re-cut — far tighter than inferring it from text diffs alone. Output:
``data/en_asset_mtimes.json`` = ``{"<bundle>/<scenario_id>": "<http date>"}``.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

EN_CDN = "https://storage.sekai.best/sekai-en-assets"
MASTER = Path("data/master")

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"


def head(url: str) -> dict | None:
    for attempt in range(3):
        try:
            resp = _session.head(url, timeout=45, allow_redirects=True)
            if resp.status_code != 200:
                return None
            return {
                "last_modified": resp.headers.get("last-modified"),
                "etag": resp.headers.get("etag", "").strip('"'),
                "size": int(resp.headers.get("content-length", 0) or 0),
            }
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return None
            time.sleep(2)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/en_asset_mtimes.json")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    stories = json.loads((MASTER / "eventStories.json").read_text())
    targets: list[tuple[int, int, str, str]] = []
    for story in stories:
        for ep in story.get("eventStoryEpisodes", []):
            targets.append(
                (story["eventId"], ep["episodeNo"], story["assetbundleName"], ep["scenarioId"])
            )

    def work(t: tuple[int, int, str, str]) -> tuple[str, dict | None]:
        event_id, episode_no, bundle, scenario_id = t
        info = head(f"{EN_CDN}/event_story/{bundle}/scenario/{scenario_id}.asset")
        if info:
            info.update({"event_id": event_id, "episode_no": episode_no})
        return f"{bundle}/{scenario_id}", info

    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, (key, info) in enumerate(pool.map(work, targets), 1):
            if info:
                out[key] = info
            if i % 200 == 0:
                print(f"  {i}/{len(targets)} ok={len(out)}")
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(out)} entries")


if __name__ == "__main__":
    main()
