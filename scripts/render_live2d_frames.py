"""Render one before/after frame per changed line over the real Live2D scene.

Generalises ``render_live2d_prototype.py`` from a --pick list to the whole diff. Each
frame stacks two game-shaped panels of the same moment — the old line above the new —
drawn over the scene the game actually shows at that ``TalkData`` index: the live
background, every on-stage character posed with their body motion and expression,
plus whatever scene state the special effects have left behind (flashback dim,
ambient colour grade, a fade still covering the screen).

    $P scripts/render_live2d_frames.py --pick 3:19        # sanity check
    $P scripts/render_live2d_frames.py                    # the full run

Output tree::

    data/images_live2d/<event>/<episode>/<index>_<speaker>.jpg
    data/images_live2d/index.json

Nothing is skipped silently: every line that cannot be drawn faithfully is recorded
with a reason in ``index.json`` and summarised on stdout at the end.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from live2d_scene import (  # noqa: E402
    DEPTH_STEP,
    Live2DStage,
    compose_scene,
    scene_states,
    stage_states,
)
from render_frames import (  # noqa: E402
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_JP,
    FONT_ROUND,
    INK,
    NEW_MARK,
    OLD_MARK,
    cached,
    cover,
    diff_spans,
    draw_spans,
    font,
    slug,
    wrap_spans,
)

PANEL_W, PANEL_H = 1920, 1080
MASTER = Path("data/master")


def character_flip_flags() -> set[int]:
    """Character2dIds whose model the game is allowed to mirror."""
    rows = json.loads((MASTER / "character2ds.json").read_text())
    return {r["id"] for r in rows if r.get("isEnabledFlipDisplay")}


def panel(
    scene: Image.Image,
    speaker: str,
    spans: list[tuple[str, bool]],
    mark_color: tuple[int, int, int],
    label: str,
    label_color: tuple[int, int, int],
) -> Image.Image:
    """One game-shaped frame: the scene with a single dialogue window at the bottom."""
    canvas = scene.copy().convert("RGBA")
    left, right = 120, PANEL_W - 120

    for size, leading in ((44, 60), (40, 55), (36, 50)):
        body_font = font(FONT_BODY, size)
        lines = wrap_spans(spans, body_font, right - left - 130)
        if len(lines) <= 3:
            break
    bold_font = font(FONT_BODY_BOLD, size)

    height = max(150, 92 + len(lines) * leading)
    top = PANEL_H - height - 56
    box = Image.new("RGBA", (right - left, height), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle(
        (0, 0, right - left - 1, height - 1), radius=48, fill=(255, 255, 255, 237)
    )
    canvas.alpha_composite(box, (left, top))

    draw = ImageDraw.Draw(canvas)
    name_font = font(FONT_ROUND, 36)
    label_font = font(FONT_ROUND, 26)
    plate_w = int(name_font.getlength(speaker)) + 78
    draw.rounded_rectangle(
        (left + 34, top - 32, left + 34 + plate_w, top + 30), radius=32, fill=(93, 88, 130)
    )
    draw.ellipse((left + 54, top - 8, left + 70, top + 8), fill=(112, 222, 219))
    draw.text((left + 80, top - 21), speaker, font=name_font, fill=(255, 255, 255))

    tag_x = left + 54 + plate_w
    tag_w = int(label_font.getlength(label)) + 36
    draw.rounded_rectangle((tag_x, top - 29, tag_x + tag_w, top + 27), radius=28, fill=label_color)
    draw.text((tag_x + 18, top - 17), label, font=label_font, fill=(255, 255, 255))

    draw_spans(canvas, lines, (left + 64, top + 56), body_font, bold_font, leading, INK, mark_color)
    return canvas


def stacked_frame(
    scene: Image.Image,
    header: str,
    subheader: str,
    speaker_old: str,
    speaker_new: str,
    old: str,
    new: str,
    jp: str,
    versions: tuple[str, str],
    out_path: Path,
    width: int = 1500,
) -> None:
    """Old view on top, new view below — two game frames of the same moment."""
    spans_old, spans_new = diff_spans(old, new)
    top_panel = panel(scene, speaker_old, spans_old, OLD_MARK, f"BEFORE  {versions[0]}", (176, 68, 68))
    bottom_panel = panel(scene, speaker_new, spans_new, NEW_MARK, f"AFTER  {versions[1]}", (46, 128, 96))

    footer = 78 if jp else 12
    canvas = Image.new("RGBA", (PANEL_W, PANEL_H * 2 + 10 + footer), (16, 14, 28, 255))
    canvas.alpha_composite(top_panel, (0, 0))
    canvas.alpha_composite(bottom_panel, (0, PANEL_H + 10))

    draw = ImageDraw.Draw(canvas)
    bar = Image.new("RGBA", (1180, 190), (0, 0, 0, 0))
    ImageDraw.Draw(bar).rounded_rectangle((0, 0, 1179, 189), radius=34, fill=(24, 20, 44, 210))
    canvas.alpha_composite(bar, (0, -40))
    draw.text((60, 34), header, font=font(FONT_ROUND, 42), fill=(255, 255, 255))
    draw.text((60, 92), subheader, font=font(FONT_BODY, 31), fill=(198, 195, 225))
    if jp:
        draw.text((120, PANEL_H * 2 + 28), f"JP  {jp}", font=font(FONT_JP, 30), fill=(214, 211, 236))

    scale = width / PANEL_W
    out = canvas.convert("RGB").resize((width, int(canvas.height * scale)), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, quality=92)


def backdrop(state: dict, notes: list[str]) -> Image.Image | None:
    """The scene behind the characters: a still, the live background, or a fade."""
    if state["cover"]:
        # a fade left the screen covered — the game shows the line over flat colour
        notes.append(f"cover:{state['cover']}")
        fill = (0, 0, 0) if state["cover"] == "black" else (255, 255, 255)
        return Image.new("RGB", (PANEL_W, PANEL_H), fill)

    if state["still"]:
        # ChangeCardStill / ChangeBackgroundStill: not on the background CDN path the
        # mirror serves, and sekai-viewer does not implement them either
        still = cached(f"scenario/background/{state['still']}/{state['still']}.webp")
        if still:
            notes.append(f"still:{state['still']}")
            return cover(Image.open(still).convert("RGB"), (PANEL_W, PANEL_H))
        notes.append(f"still-unresolved:{state['still']}")

    name = state["background"]
    if not name:
        notes.append("no-background")
        return None
    path = cached(f"scenario/background/{name}/{name}.webp")
    if not path:
        notes.append(f"background-missing:{name}")
        return None
    return cover(Image.open(path).convert("RGB"), (PANEL_W, PANEL_H))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/transitions/event_story__event_stella_2020__scenario__5.4.0.20__5.4.0.30.json")
    ap.add_argument("--out", default="data/images_live2d")
    ap.add_argument("--kinds", default="text,speaker")
    ap.add_argument("--pick", default="", help="episode:talk_index pairs, for spot checks")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--pose-time",
        type=float,
        default=-1.0,
        help="seconds into each motion; <0 samples the settled end pose (default)",
    )
    ap.add_argument("--flip", action="store_true", help="mirror models with isEnabledFlipDisplay")
    ap.add_argument("--depth-step", type=float, default=DEPTH_STEP)
    ap.add_argument("--suffix", default="", help="appended to filenames, for A/B renders")
    args = ap.parse_args()

    pose_time = None if args.pose_time < 0 else args.pose_time
    data = json.loads(Path(args.changes).read_text())
    old_ver = data["comparison"]["old_asset_version"]
    new_ver = data["comparison"]["new_asset_version"]
    kinds = set(args.kinds.split(","))
    flip_ids = character_flip_flags() if args.flip else set()

    wanted: dict[int, set[int]] = {}
    for pair in filter(None, args.pick.split(",")):
        ep_no, idx = pair.split(":")
        wanted.setdefault(int(ep_no), set()).add(int(idx))

    stage = Live2DStage(size=(PANEL_W, PANEL_H))
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    index: list[dict] = []
    dropped: list[dict] = []
    note_counts: Counter[str] = Counter()
    depth_seen: Counter[int] = Counter()
    rendered = 0
    started = time.time()

    for event in data["events"]:
        event_dir = out_root / f"event_{event['event_id']:03d}_{slug(event['name_en'])}"
        bundle_name = event["bundle"].split("/")[1]
        scenarios = json.loads(
            Path("data/official", new_ver, event["bundle"].replace("/", "__") + ".json").read_text()
        )["scenarios"]

        for ep in event["episodes"]:
            if wanted and ep["episode_no"] not in wanted:
                continue
            scenario = scenarios[ep["scenario_id"]]
            states = stage_states(scenario)
            scenes = scene_states(scenario)
            layout_mode = "three_models" if scenario.get("FirstCharacterLayoutMode") == 1 else "normal"
            for row in scenario.get("LayoutData") or []:
                depth_seen[row.get("DepthType", 0) or 0] += 1

            jp_path = Path("data/jp_assets") / bundle_name / f"{ep['scenario_id']}.json"
            jp_lines = (
                [(t.get("Body") or "").replace("\n", "") for t in json.loads(jp_path.read_text())["TalkData"]]
                if jp_path.exists()
                else []
            )

            ep_dir = event_dir / f"ep{ep['episode_no']:02d}_{slug(ep['title_en'])}"
            for change in ep["changes"]:
                if change["kind"] not in kinds:
                    continue
                idx = change["talk_index_new"]
                if idx is None:
                    dropped.append({**_ref(event, ep, change), "reason": "no talk index in new version"})
                    continue
                if wanted and idx not in wanted[ep["episode_no"]]:
                    continue

                notes: list[str] = []
                state = scenes.get(idx) or {
                    "background": scenario.get("FirstBackground") or "",
                    "still": "",
                    "flashback": False,
                    "ambient": "normal",
                    "cover": "",
                }
                background = backdrop(state, notes)
                if background is None:
                    dropped.append({**_ref(event, ep, change), "reason": ", ".join(notes)})
                    continue

                characters = states.get(idx, [])
                scene = compose_scene(
                    stage,
                    background,
                    characters,
                    layout_mode=layout_mode,
                    flip_ids=flip_ids,
                    pose_time=pose_time,
                    ambient=state["ambient"],
                    depth_step=args.depth_step,
                )
                if state["flashback"]:
                    # sekai-viewer's flashback_filter: flat black at 0.3 over the scene,
                    # under the dialogue box
                    notes.append("flashback")
                    scene.alpha_composite(Image.new("RGBA", scene.size, (0, 0, 0, 77)))
                if not characters:
                    notes.append("no-characters")
                if state["ambient"] != "normal":
                    notes.append(f"ambient:{state['ambient']}")

                speaker_new = change["speaker_new"] or change["speaker_old"] or "—"
                speaker_old = change["speaker_old"] or speaker_new
                out_path = ep_dir / f"{idx:03d}_{slug(speaker_new, 18)}{args.suffix}.jpg"
                stacked_frame(
                    scene,
                    event["name_en"],
                    f"Episode {ep['episode_no']} - {ep['title_en']}   |   line #{idx}",
                    speaker_old,
                    speaker_new,
                    change["old"],
                    change["new"],
                    jp_lines[idx] if idx < len(jp_lines) else "",
                    (old_ver, new_ver),
                    out_path,
                )
                note_counts.update(n.split(":")[0] for n in notes)
                index.append(
                    {
                        "path": str(out_path),
                        "event_id": event["event_id"],
                        "episode_no": ep["episode_no"],
                        "talk_index": idx,
                        "speaker": speaker_new,
                        "kind": change["kind"],
                        "cast": [c["costume"] for c in characters],
                        "background": state["background"],
                        "notes": notes,
                    }
                )
                rendered += 1
                if rendered % 25 == 0:
                    rate = rendered / max(1e-6, time.time() - started)
                    print(f"  {rendered} frames ({rate:.1f}/s)")
                if args.limit and rendered >= args.limit:
                    break

    Path(out_root, "index.json").write_text(
        json.dumps({"frames": index, "dropped": dropped}, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )

    total = sum(1 for e in data["events"] for p in e["episodes"] for c in p["changes"] if c["kind"] in kinds)
    print(f"\nrendered {rendered} frames into {out_root} in {time.time() - started:.0f}s")
    print(f"eligible changes of kind {sorted(kinds)}: {total}")
    if not args.pick and not args.limit:
        print(f"accounted for: {rendered} rendered + {len(dropped)} dropped = {rendered + len(dropped)}")
    for reason, count in Counter(d["reason"] for d in dropped).most_common():
        print(f"  DROPPED {count}: {reason}")
    for note, count in note_counts.most_common():
        print(f"  note {note}: {count}")
    print(f"  DepthType histogram across LayoutData: {dict(depth_seen)}")


def _ref(event: dict, ep: dict, change: dict) -> dict:
    return {
        "event_id": event["event_id"],
        "episode_no": ep["episode_no"],
        "talk_index": change["talk_index_new"],
        "speaker": change["speaker_new"] or change["speaker_old"],
        "kind": change["kind"],
    }


if __name__ == "__main__":
    main()
