"""Diff two pinned official EN asset versions, line by line.

Both sides are official ``ScenarioData`` typetrees pulled from the game CDN, so the
comparison is index-for-index on ``TalkData`` — no fuzzy transcript alignment. Any
count mismatch falls back to a sequence alignment so inserted/removed lines are
reported as such instead of smearing the rest of the episode.

Output: ``data/official_changes.json``.
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
from textutil import compare_key, language_shift, normalize  # noqa: E402

MASTER = Path("data/master")
OFFICIAL = Path("data/official")
# The story indexer supplies the JP name / unit / arc slug. This used to be read as a
# bare "events_index.json" from the current working directory — a file that does not
# exist in this repo, so the script only ran from a scratch cwd with a copy dropped in.
INDEXER = Path.home() / "github/sekai-story-indexer/events_index.json"


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
    # rewrite | localised | untranslated | japanese. An EN asset does not always hold
    # English: most catalogue-wide "changes" are the first localisation landing, not an
    # edit, and must not be shown as retranslation.
    lang: str = "rewrite"


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
                    language_shift("", _flat(n.get("Body"))),
                )
            )
            return
        if j is None:
            changes.append(
                LineChange(
                    i, None, "removed", (o.get("WindowDisplayName") or "").strip(), "",
                    _flat(o.get("Body")), "", 0.0,
                    language_shift(_flat(o.get("Body")), ""),
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
                language_shift(old_text, new_text),
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
    ap.add_argument(
        "--out",
        default="",
        help="output path; defaults to data/official_changes_<old>_<new>.json",
    )
    ap.add_argument("--indexer", default=str(INDEXER), help="sekai-story-indexer events_index.json")
    ap.add_argument(
        "--bundles",
        nargs="*",
        default=[],
        help="restrict to these bundles (e.g. event_story/event_stella_2020/scenario)",
    )
    ap.add_argument(
        "--old-released-at",
        default="",
        help="ISO date the old assetVersion shipped, carried into the web snapshots",
    )
    ap.add_argument(
        "--new-released-at",
        default="",
        help="ISO date the new assetVersion shipped",
    )
    args = ap.parse_args()

    stories = json.loads((MASTER / "eventStories.json").read_text())
    by_bundle = {f"event_story/{s['assetbundleName']}/scenario": s for s in stories}
    en_events = {e["id"]: e for e in json.loads((MASTER / "events_en.json").read_text())}
    en_titles = {
        s["eventId"]: {ep["episodeNo"]: ep.get("title", "") for ep in s.get("eventStoryEpisodes", [])}
        for s in json.loads((MASTER / "eventStories_en.json").read_text())
    }
    index_path = Path(args.indexer)
    if not index_path.exists():
        raise SystemExit(
            f"{index_path} not found — it supplies each event's JP name, unit and arc slug. "
            "Pass --indexer, or clone sekai-story-indexer next to this repo."
        )
    index = {e["event_id"]: e for e in json.loads(index_path.read_text())}

    old_root, new_root = OFFICIAL / args.old, OFFICIAL / args.new
    events: list[dict] = []
    only_new: list[str] = []

    wanted = {b.replace("/", "__") + ".json" for b in args.bundles}
    for new_path in sorted(new_root.glob("*.json")):
        if wanted and new_path.name not in wanted:
            continue
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
        # The scenario files inside a bundle are not always named after the EN eventId:
        # event_higher_2025 is eventId 169 but holds event_168_*, and cheerheart (168)
        # holds event_167_*. The filenames follow JP production numbering while the EN
        # region numbers its own events, and the two have drifted. Matching on the
        # scenarioId string silently yields no episode at all, so fall back to the
        # episode number in the filename.
        ep_by_number = {
            ep.get("episodeNo"): ep for ep in master.get("eventStoryEpisodes", [])
        }

        episodes: list[dict] = []
        for name, new_scenario in sorted(new_doc["scenarios"].items()):
            old_scenario = old_doc["scenarios"].get(name)
            if old_scenario is None:
                continue
            changes = diff_scenario(old_scenario, new_scenario)
            if not changes:
                continue
            trailing = re.search(r"_(\d+)$", name)
            number = int(trailing.group(1)) if trailing else None
            ep = ep_by_scenario.get(name) or ep_by_number.get(number) or {}
            episode_no = ep.get("episodeNo") or number
            episodes.append(
                {
                    "scenario_id": name,
                    "episode_no": episode_no,
                    "title_en": en_titles.get(master["eventId"], {}).get(episode_no, ""),
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
    langs: dict[str, int] = {}
    for event in events:
        for ep in event["episodes"]:
            for c in ep["changes"]:
                kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
                langs[c["lang"]] = langs.get(c["lang"], 0) + 1
    payload = {
        "comparison": {
            "old_asset_version": args.old,
            "new_asset_version": args.new,
            "old_released_at": args.old_released_at,
            "new_released_at": args.new_released_at,
            "region": "en",
            "source": "official game CDN (n-production-*-assetbundle.sekai-en.com)",
        },
        "totals": {
            "events_changed": len(events),
            "episodes_changed": sum(len(e["episodes"]) for e in events),
            "changed_lines": sum(e["total_changes"] for e in events),
            "by_kind": kinds,
            "by_lang": langs,
            "rewrite_lines": langs.get("rewrite", 0),
        },
        "events": events,
        "bundles_only_in_new": only_new,
    }
    out_path = Path(args.out or f"data/official_changes_{args.old}_{args.new}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {out_path}")
    print(json.dumps(payload["totals"], indent=1))


if __name__ == "__main__":
    main()
