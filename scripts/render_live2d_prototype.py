"""Prototype: before/after frames drawn over the real reconstructed Live2D scene.

Same comparison layout as ``render_frames.py``, but the backdrop is the actual staged
scene (posed characters over the live background) instead of a background + portrait.

    .venv/bin/python scripts/data/render_live2d_prototype.py
    .venv/bin/python scripts/data/render_live2d_prototype.py --pick 3:19,6:30
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from live2d_scene import Live2DStage, compose_scene, stage_states  # noqa: E402
from PIL import ImageDraw  # noqa: E402
from render_frames import (  # noqa: E402
    FONT_BODY,
    FONT_JP,
    FONT_ROUND,
    INK,
    NEW_MARK,
    OLD_MARK,
    background_by_talk,
    cached,
    cover,
    diff_spans,
    draw_spans,
    font,
    slug,
    wrap_spans,
)

PANEL_W, PANEL_H = 1920, 1080


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
    bold_font = font(FONT_BODY_BOLD_PATH, size)

    height = max(210, 92 + len(lines) * leading)
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


FONT_BODY_BOLD_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def stacked_frame(
    scene: Image.Image,
    header: str,
    subheader: str,
    speaker: str,
    old: str,
    new: str,
    jp: str,
    versions: tuple[str, str],
    out_path: Path,
    width: int = 1500,
) -> None:
    """Old view on top, new view below — two game frames of the same moment."""
    spans_old, spans_new = diff_spans(old, new)
    top_panel = panel(scene, speaker, spans_old, OLD_MARK, f"BEFORE  {versions[0]}", (176, 68, 68))
    bottom_panel = panel(scene, speaker, spans_new, NEW_MARK, f"AFTER  {versions[1]}", (46, 128, 96))

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
        draw.text(
            (120, PANEL_H * 2 + 28),
            f"JP  {jp}",
            font=font(FONT_JP, 30),
            fill=(214, 211, 236),
        )

    scale = width / PANEL_W
    out = canvas.convert("RGB").resize((width, int(canvas.height * scale)), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path, quality=92)

# A spread that exercises the interesting cases: two-hander, solo, off-screen
# speaker ("Tsukasa's Voice"), night exterior, crowd scene, finale.
DEFAULT_PICKS = "1:13,2:48,3:19,3:21,6:47,8:23"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument("--out", default="data/images_live2d")
    ap.add_argument("--pick", default=DEFAULT_PICKS, help="episode:talk_index pairs")
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    event = data["events"][0]
    old_ver = data["comparison"]["old_asset_version"]
    new_ver = data["comparison"]["new_asset_version"]
    bundle_name = event["bundle"].split("/")[1]

    scenarios = json.loads(
        Path("data/official", new_ver, event["bundle"].replace("/", "__") + ".json").read_text()
    )["scenarios"]
    wanted: dict[int, set[int]] = {}
    for pair in args.pick.split(","):
        ep_no, idx = pair.split(":")
        wanted.setdefault(int(ep_no), set()).add(int(idx))

    stage = Live2DStage(size=(PANEL_W, PANEL_H))
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    made = 0

    for ep in event["episodes"]:
        if ep["episode_no"] not in wanted:
            continue
        scenario = scenarios[ep["scenario_id"]]
        states = stage_states(scenario)
        bg_map = background_by_talk(scenario)
        jp_path = Path("data/jp_assets") / bundle_name / f"{ep['scenario_id']}.json"
        jp_lines = (
            [(t.get("Body") or "").replace("\n", "") for t in json.loads(jp_path.read_text())["TalkData"]]
            if jp_path.exists()
            else []
        )

        for change in ep["changes"]:
            idx = change["talk_index_new"]
            if idx not in wanted[ep["episode_no"]]:
                continue
            bg_name = bg_map.get(idx) or scenario.get("FirstBackground") or ""
            bg_path = cached(f"scenario/background/{bg_name}/{bg_name}.webp")
            if not bg_path:
                print(f"  ep{ep['episode_no']} #{idx}: no background {bg_name}")
                continue
            background = cover(Image.open(bg_path).convert("RGB"), (1920, 1080))
            characters = states.get(idx, [])
            scene = compose_scene(stage, background, characters)
            speaker = change["speaker_new"] or change["speaker_old"] or "—"
            out_path = out_root / f"ep{ep['episode_no']:02d}_{idx:03d}_{slug(speaker, 18)}.jpg"
            stacked_frame(
                scene,
                f"Event {event['event_id']}  |  {event['name_en']}",
                f"Episode {ep['episode_no']} - {ep['title_en']}   |   line #{idx}",
                speaker,
                change["old"],
                change["new"],
                jp_lines[idx] if idx < len(jp_lines) else "",
                (old_ver, new_ver),
                out_path,
            )
            cast = ", ".join(c["costume"] for c in characters) or "(no one on stage)"
            print(f"  ep{ep['episode_no']} #{idx} {speaker}: {cast}")
            made += 1

    print(f"rendered {made} prototype frames into {out_root}")


if __name__ == "__main__":
    main()
