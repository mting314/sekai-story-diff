"""Cache the *current* official-EN event-story scenario assets.

The EN CDN mirrors the JP asset layout, so ``eventStories.json`` (master DB) gives us
every ``(assetbundleName, scenarioId)`` pair and we pull the EN ``.asset`` JSON for
each episode into ``data/en_assets/<bundle>/<scenarioId>.json``.

These are the *new* (post-retranslation) lines; the pinned old version holds the previous ones.
The raw scenario JSON also carries the layout/background/character data that the
phase-2 image renderer needs, which is why we keep the whole asset, not just Body.
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

MASTER_DB = "https://sekai-world.github.io/sekai-master-db-diff"
EN_CDN = "https://storage.sekai.best/sekai-en-assets"
OUT = Path("data/en_assets")

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"


def _get_json(url: str) -> dict | list | None:
    for attempt in range(4):
        try:
            resp = _session.get(url, timeout=90)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception:  # noqa: BLE001 - transient CDN errors
            if attempt == 3:
                return None
            time.sleep(2 * (attempt + 1))
    return None


def event_episodes() -> list[dict]:
    """``[{event_id, bundle, episode_no, scenario_id, title_jp}]`` for every event episode."""
    stories = _get_json(f"{MASTER_DB}/eventStories.json") or []
    rows: list[dict] = []
    for story in stories:
        bundle = story["assetbundleName"]
        for ep in story.get("eventStoryEpisodes", []):
            rows.append(
                {
                    "event_id": story["eventId"],
                    "bundle": bundle,
                    "episode_no": ep["episodeNo"],
                    "scenario_id": ep["scenarioId"],
                    "title_jp": ep.get("title", ""),
                }
            )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-event", type=int, default=0, help="only events with id <= N")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = event_episodes()
    if args.max_event:
        rows = [r for r in rows if r["event_id"] <= args.max_event]
    print(f"{len(rows)} event episodes")

    def work(row: dict) -> str:
        dest = out / row["bundle"] / f"{row['scenario_id']}.json"
        if dest.exists() and not args.refresh:
            return "cached"
        url = f"{EN_CDN}/event_story/{row['bundle']}/scenario/{row['scenario_id']}.asset"
        data = _get_json(url)
        if not data:
            return "missing"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return "fetched"

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, status in enumerate(pool.map(work, rows), 1):
            counts[status] = counts.get(status, 0) + 1
            if i % 100 == 0:
                print(f"  {i}/{len(rows)} {counts}")
    print("done:", counts)


if __name__ == "__main__":
    main()
