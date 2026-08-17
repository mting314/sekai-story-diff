"""Diff two pinned official EN asset versions, line by line.

Both sides are official ``ScenarioData`` typetrees pulled from the game CDN, so the
comparison is index-for-index on ``TalkData`` — no fuzzy transcript alignment. Any
count mismatch falls back to a sequence alignment so inserted/removed lines are
reported as such instead of smearing the rest of the episode.

Output: ``retranslation/official_changes.json``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from textutil import compare_key, normalize  # noqa: E402

MASTER = Path("retranslation/master")
OFFICIAL = Path("retranslation/official")


@dataclass
class LineChange:
    talk_index_old: int | None
    talk_index_new: int | None
    kind: str  # text | linebreak | speaker | added | removed
    speaker_old: str
    speaker_new: str
    old: str
    new: str
    ratio: float


def _flat(body: str) -> str:
    return re.sub(r"\s+", " ", (body or "").replace("\n", " ")).strip()


def _talks(scenario: dict) -> list[dict]:
    return scenario.get("TalkData") or []


def _classify(old: dict, new: dict) -> str | None:
    old_body, new_body = old.get("Body") or "", new.get("Body") or ""
    old_name = (old.get("WindowDisplayName") or "").strip()
    new_name = (new.get("WindowDisplayName") or "").strip()
    if normalize(_flat(old_body)) != normalize(_flat(new_body)):
        return "text"
    if old_body != new_body:
        return "linebreak"
    if old_name != new_name:
        return "speaker"
    return None


def diff_scenario(old: dict, new: dict) -> list[LineChange]:
    talks_old, talks_new = _talks(old), _talks(new)
    changes: list[LineChange] = []

    def emit(i: int | None, j: int | None) -> None:
        o = talks_old[i] if i is not None else {}
        n = talks_new[j] if j is not None else {}
        if i is None:
            changes.append(
                LineChange(
                    None, j, "added", "", (n.get("WindowDisplayName") or "").strip(),
                    "", _flat(n.get("Body")), 0.0,
                )
            )
            return
        if j is None:
            changes.append(
                LineChange(
                    i, None, "removed", (o.get("WindowDisplayName") or "").strip(), "",
                    _flat(o.get("Body")), "", 0.0,
                )
            )
            return
        kind = _classify(o, n)
        if not kind:
            return
        old_text, new_text = _flat(o.get("Body")), _flat(n.get("Body"))
        changes.append(
            LineChange(
                i,
                j,
                kind,
                (o.get("WindowDisplayName") or "").strip(),
                (n.get("WindowDisplayName") or "").strip(),
                old_text,
                new_text,
                round(SequenceMatcher(None, compare_key(old_text), compare_key(new_text)).ratio(), 3),
            )
        )

    if len(talks_old) == len(talks_new):
        for idx in range(len(talks_old)):
            emit(idx, idx)
        return changes

    keys_old = [compare_key(_flat(t.get("Body"))) for t in talks_old]
    keys_new = [compare_key(_flat(t.get("Body"))) for t in talks_new]
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, keys_old, keys_new).get_opcodes():
        if tag == "equal":
            for off in range(i2 - i1):
                emit(i1 + off, j1 + off)
        elif tag == "replace":
            span = min(i2 - i1, j2 - j1)
            for off in range(span):
                emit(i1 + off, j1 + off)
            for i in range(i1 + span, i2):
                emit(i, None)
            for j in range(j1 + span, j2):
                emit(None, j)
        elif tag == "delete":
            for i in range(i1, i2):
                emit(i, None)
        else:
            for j in range(j1, j2):
                emit(None, j)
    return changes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True, help="old assetVersion directory name")
    ap.add_argument("--new", required=True, help="new assetVersion directory name")
    ap.add_argument("--out", default="retranslation/official_changes.json")
    args = ap.parse_args()

    stories = json.loads((MASTER / "eventStories.json").read_text())
    by_bundle = {f"event_story/{s['assetbundleName']}/scenario": s for s in stories}
    en_events = {e["id"]: e for e in json.loads((MASTER / "events_en.json").read_text())}
    en_titles = {
        s["eventId"]: {ep["episodeNo"]: ep.get("title", "") for ep in s.get("eventStoryEpisodes", [])}
        for s in json.loads((MASTER / "eventStories_en.json").read_text())
    }
    index = {e["event_id"]: e for e in json.loads(Path("events_index.json").read_text())}

    old_root, new_root = OFFICIAL / args.old, OFFICIAL / args.new
    events: list[dict] = []
    only_new: list[str] = []

    for new_path in sorted(new_root.glob("*.json")):
        old_path = old_root / new_path.name
        new_doc = json.loads(new_path.read_text())
        bundle = new_doc["bundle"]
        if not old_path.exists():
            only_new.append(bundle)
            continue
        old_doc = json.loads(old_path.read_text())
        master = by_bundle.get(bundle)
        if not master:
            continue
        ep_by_scenario = {
            ep["scenarioId"]: ep for ep in master.get("eventStoryEpisodes", [])
        }

        episodes: list[dict] = []
        for name, new_scenario in sorted(new_doc["scenarios"].items()):
            old_scenario = old_doc["scenarios"].get(name)
            if old_scenario is None:
                continue
            changes = diff_scenario(old_scenario, new_scenario)
            if not changes:
                continue
            ep = ep_by_scenario.get(name, {})
            episodes.append(
                {
                    "scenario_id": name,
                    "episode_no": ep.get("episodeNo"),
                    "title_en": en_titles.get(master["eventId"], {}).get(ep.get("episodeNo"), ""),
                    "title_jp": ep.get("title", ""),
                    "lines_old": len(_talks(old_scenario)),
                    "lines_new": len(_talks(new_scenario)),
                    "changes": [asdict(c) for c in changes],
                }
            )
        if not episodes:
            continue
        event_id = master["eventId"]
        meta = index.get(event_id, {})
        episodes.sort(key=lambda e: (e["episode_no"] or 0, e["scenario_id"]))
        events.append(
            {
                "event_id": event_id,
                "name_en": en_events.get(event_id, {}).get("name", ""),
                "name_jp": meta.get("name", ""),
                "unit": meta.get("unit", ""),
                "arc_slug": meta.get("arc_slug", ""),
                "bundle": bundle,
                "episodes": episodes,
                "total_changes": sum(len(e["changes"]) for e in episodes),
                "text_changes": sum(
                    1 for e in episodes for c in e["changes"] if c["kind"] == "text"
                ),
            }
        )

    events.sort(key=lambda e: e["event_id"])
    kinds: dict[str, int] = {}
    for event in events:
        for ep in event["episodes"]:
            for c in ep["changes"]:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    payload = {
        "comparison": {
            "old_asset_version": args.old,
            "new_asset_version": args.new,
            "region": "en",
            "source": "official game CDN (n-production-*-assetbundle.sekai-en.com)",
        },
        "totals": {
            "events_changed": len(events),
            "episodes_changed": sum(len(e["episodes"]) for e in events),
            "changed_lines": sum(e["total_changes"] for e in events),
            "by_kind": kinds,
        },
        "events": events,
        "bundles_only_in_new": only_new,
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(payload["totals"], indent=1))


if __name__ == "__main__":
    main()
