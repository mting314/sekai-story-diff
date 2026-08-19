"""Render the official-vs-official line changes as Markdown + CSV.

Adds the Japanese line for each changed index (same ``TalkData`` order as EN) so a
reader can judge the rewrite against the source, and marks the changed words.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
from pathlib import Path

import requests

JP_CDN = "https://storage.sekai.best/sekai-jp-assets"
JP_CACHE = Path("data/jp_assets")

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"


def jp_lines(bundle: str, scenario_id: str) -> list[str]:
    """JP ``Body`` per TalkData index (cached)."""
    dest = JP_CACHE / bundle / f"{scenario_id}.json"
    if not dest.exists():
        url = f"{JP_CDN}/event_story/{bundle}/scenario/{scenario_id}.asset"
        try:
            resp = _session.get(url, timeout=60)
            if resp.status_code != 200:
                return []
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(resp.json(), ensure_ascii=False), encoding="utf-8")
        except Exception:  # noqa: BLE001
            return []
    data = json.loads(dest.read_text())
    return [(t.get("Body") or "").replace("\n", "") for t in data.get("TalkData", [])]


def word_diff(old: str, new: str) -> tuple[str, str]:
    """Bold the words that differ on each side."""
    # Exact comparison: case and punctuation differences are real edits here.
    old_words, new_words = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    out_old: list[str] = []
    out_new: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out_old += old_words[i1:i2]
            out_new += new_words[j1:j2]
        else:
            if i2 > i1:
                out_old.append("**" + " ".join(old_words[i1:i2]) + "**")
            if j2 > j1:
                out_new.append("**" + " ".join(new_words[j1:j2]) + "**")
    return " ".join(out_old), " ".join(out_new)


def _esc(text: str) -> str:
    return re.sub(r"([|])", r"\\\1", text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/transitions/event_story__event_stella_2020__scenario__5.4.0.20__5.4.0.30.json")
    ap.add_argument("--out-md", default="data/REPORT.md")
    ap.add_argument("--out-csv", default="data/changed_lines.csv")
    ap.add_argument("--skip-jp", action="store_true")
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    cmp_info = data["comparison"]
    totals = data["totals"]

    lines: list[str] = []
    lines.append("# Official EN retranslation — changed lines")
    lines.append("")
    lines.append(
        f"Diff of the official English scenario assets between EN asset version "
        f"**{cmp_info['old_asset_version']}** and **{cmp_info['new_asset_version']}** "
        f"(the release that rewrote the lines in question)."
    )
    lines.append("")
    lines.append("| | |")
    lines.append("|---|---|")
    lines.append(f"| Source | {cmp_info['source']} |")
    lines.append(f"| Old version | `{cmp_info['old_asset_version']}` |")
    lines.append(f"| New version | `{cmp_info['new_asset_version']}` |")
    lines.append(f"| Events changed | {totals['events_changed']} |")
    lines.append(f"| Episodes changed | {totals['episodes_changed']} |")
    lines.append(f"| Changed lines | {totals['changed_lines']} |")
    for kind, count in sorted(totals["by_kind"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| … {kind} | {count} |")
    lines.append("")
    lines.append(
        "`text` = wording changed · `linebreak` = same words, different on-screen "
        "line wrap · `speaker` = name-plate changed."
    )
    lines.append("")

    rows: list[dict] = []
    for event in data["events"]:
        lines.append(
            f"## {event['name_en']} — {event['name_jp']}"
        )
        lines.append("")
        lines.append(
            f"Unit `{event['unit']}` · bundle `{event['bundle']}` · "
            f"{event['total_changes']} changed lines across {len(event['episodes'])} episodes."
        )
        lines.append("")
        bundle_name = event["bundle"].split("/")[1]
        for ep in event["episodes"]:
            jp = [] if args.skip_jp else jp_lines(bundle_name, ep["scenario_id"])
            lines.append(
                f"### Episode {ep['episode_no']} — {ep['title_en']} "
                f"（{ep['title_jp']}） · `{ep['scenario_id']}`"
            )
            lines.append("")
            lines.append(f"{len(ep['changes'])} changed lines of {ep['lines_new']}.")
            lines.append("")
            for change in ep["changes"]:
                idx = change["talk_index_new"]
                if change["kind"] == "linebreak":
                    continue
                speaker = change["speaker_new"] or change["speaker_old"] or "—"
                marked_old, marked_new = word_diff(change["old"], change["new"])
                lines.append(f"**#{idx} · {speaker}** · _{change['kind']}_")
                lines.append("")
                lines.append(f"- OLD: {_esc(marked_old) or '—'}")
                lines.append(f"- NEW: {_esc(marked_new) or '—'}")
                if jp and idx is not None and idx < len(jp):
                    lines.append(f"- JP: {_esc(jp[idx])}")
                lines.append("")
                rows.append(
                    {
                        "event_id": event["event_id"],
                        "event_name_en": event["name_en"],
                        "episode_no": ep["episode_no"],
                        "episode_title_en": ep["title_en"],
                        "scenario_id": ep["scenario_id"],
                        "talk_index": idx,
                        "kind": change["kind"],
                        "speaker_old": change["speaker_old"],
                        "speaker_new": change["speaker_new"],
                        "old": change["old"],
                        "new": change["new"],
                        "jp": jp[idx] if jp and idx is not None and idx < len(jp) else "",
                        "similarity": change["ratio"],
                    }
                )
            wraps = [c for c in ep["changes"] if c["kind"] == "linebreak"]
            if wraps:
                indices = ", ".join(f"#{c['talk_index_new']}" for c in wraps)
                lines.append(f"_Line-wrap only (text identical): {indices}_")
                lines.append("")

    Path(args.out_md).write_text("\n".join(lines), encoding="utf-8")
    with Path(args.out_csv).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {args.out_md} ({len(lines)} lines) and {args.out_csv} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
