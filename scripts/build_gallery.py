"""Build a browsable gallery of the rendered before/after frames.

Writes ``data/images/gallery.html`` (one section per episode, images lazy
loaded) plus a ``README.md`` per episode folder so the tree reads well on GitHub.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

TEMPLATE_HEAD = """<!doctype html>
<meta charset="utf-8">
<title>{title}</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; background:#14121f; color:#eceaf6;
        font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }}
 header {{ padding:28px 40px 10px; }}
 h1 {{ margin:0 0 6px; font-size:26px; }}
 .meta {{ color:#a9a4c6; }}
 h2 {{ margin:38px 40px 6px; font-size:20px; border-top:1px solid #2c2843; padding-top:22px; }}
 .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(520px,1fr));
          gap:22px; padding:14px 40px 30px; }}
 figure {{ margin:0; background:#1c1930; border-radius:14px; overflow:hidden; }}
 img {{ width:100%; display:block; }}
 figcaption {{ padding:10px 14px 14px; font-size:13px; color:#c8c3e0; }}
 .idx {{ color:#8f89b5; }}
 .old {{ color:#ff9b9b; }} .new {{ color:#8ce0b6; }}
</style>
<header>
<h1>{title}</h1>
<div class="meta">{meta}</div>
</header>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument("--images", default="data/images")
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    index = json.loads(Path(args.images, "index.json").read_text())
    # render_frames.py writes a bare list; render_live2d_frames.py writes
    # {"frames": [...], "dropped": [...]} so unrenderable lines stay visible
    dropped = index.get("dropped", []) if isinstance(index, dict) else []
    frames = index["frames"] if isinstance(index, dict) else index
    by_key = {(i["event_id"], i["episode_no"], i["talk_index"]): i["path"] for i in frames}
    cmp_info = data["comparison"]
    root = Path(args.images)

    parts = [
        TEMPLATE_HEAD.format(
            title="Project Sekai EN — official retranslation, line by line",
            meta=(
                f"EN asset version <b>{cmp_info['old_asset_version']}</b> → "
                f"<b>{cmp_info['new_asset_version']}</b> · "
                f"{data['totals']['changed_lines']} changed lines · "
                f"source: {html.escape(cmp_info['source'])}"
            ),
        )
    ]

    for event in data["events"]:
        for ep in event["episodes"]:
            rows = [
                c
                for c in ep["changes"]
                if (event["event_id"], ep["episode_no"], c["talk_index_new"]) in by_key
            ]
            if not rows:
                continue
            parts.append(
                f"<h2>Event {event['event_id']} · {html.escape(event['name_en'])} — "
                f"Episode {ep['episode_no']}: {html.escape(ep['title_en'])} "
                f"<span class='idx'>({len(rows)} changed lines)</span></h2>"
            )
            parts.append("<div class='grid'>")
            lines_md = [
                f"# Event {event['event_id']} — {event['name_en']}",
                "",
                f"## Episode {ep['episode_no']} — {ep['title_en']} (`{ep['scenario_id']}`)",
                "",
                f"{len(rows)} changed lines, EN asset `{cmp_info['old_asset_version']}` → "
                f"`{cmp_info['new_asset_version']}`.",
                "",
            ]
            for change in rows:
                path = by_key[(event["event_id"], ep["episode_no"], change["talk_index_new"])]
                rel = Path(path).relative_to(root)
                speaker = html.escape(change["speaker_new"] or change["speaker_old"])
                parts.append(
                    f"<figure><img loading='lazy' src='{rel}'>"
                    f"<figcaption><span class='idx'>#{change['talk_index_new']}</span> "
                    f"<b>{speaker}</b><br>"
                    f"<span class='old'>− {html.escape(change['old'])}</span><br>"
                    f"<span class='new'>+ {html.escape(change['new'])}</span>"
                    "</figcaption></figure>"
                )
                lines_md += [
                    f"### #{change['talk_index_new']} · {change['speaker_new'] or change['speaker_old']}",
                    "",
                    f"![line {change['talk_index_new']}]({rel.name})",
                    "",
                    f"- **OLD:** {change['old']}",
                    f"- **NEW:** {change['new']}",
                    "",
                ]
            parts.append("</div>")
            first = by_key[(event["event_id"], ep["episode_no"], rows[0]["talk_index_new"])]
            (Path(first).parent / "README.md").write_text("\n".join(lines_md), encoding="utf-8")

    if dropped:
        parts.append(
            f"<h2>Not rendered <span class='idx'>({len(dropped)} lines)</span></h2>"
            "<div class='grid'><figure><figcaption>"
            + "<br>".join(
                f"ep{d['episode_no']} #{d['talk_index']} <b>{html.escape(d['speaker'] or '')}</b> "
                f"<span class='idx'>{html.escape(d['reason'])}</span>"
                for d in dropped
            )
            + "</figcaption></figure></div>"
        )

    out = root / "gallery.html"
    out.write_text("\n".join(parts), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
