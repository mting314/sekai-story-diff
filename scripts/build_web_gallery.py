"""Build the gallery as a static site that composes each frame in the browser.

The baked gallery ships 359 full-HD JPEGs (~193 MB) that each contain the background
twice and the dialogue text as pixels. Almost none of that has to be hosted:

* backgrounds are already on the public asset mirror — hot-link them
* the dialogue box, text and the Japanese source line are HTML, so they cost nothing,
  stay selectable and stay searchable
* only the posed characters are ours, and they dedupe hard: the sprite art depends on
  (costume, motion, facial, grade) but *not* on which side of the stage it sits, so one
  crop serves every line reusing the pose, positioned with CSS

This script produces only the data; the site itself is the Vite app in ``web/``::

    web/public/sprites/<key>.webp   cropped, alpha, one per distinct pose
    web/src/data.json               events → episodes → frames, sprite placement

Run after the diff exists, then build the site::

    $P scripts/build_web_gallery.py
    cd web && bun install && bun run build     # -> web/dist, ~30 MB

``bun run dev`` serves it with hot reload. The build uses a relative base, so
``web/dist`` works opened straight off disk as well as under a GitHub Pages project
path; set ``BASE_URL`` to override.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from itertools import groupby
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from live2d_scene import (  # noqa: E402
    LAYOUT_SCALE,
    OFFSCREEN,
    POSITION_MAPS,
    Live2DStage,
    depth_scale,
    grade,
    scene_states,
    stage_states,
)
from render_frames import diff_spans, slug  # noqa: E402

STAGE_W, STAGE_H = 1920, 1080
# the mirror the pipeline already pulls backgrounds from; the viewer hot-links it too
BG_CDN = "https://storage.sekai.best/sekai-jp-assets/scenario/background"


def sprite_key(costume: str, motion: str, facial: str, ambient: str, depth: int) -> str:
    raw = f"{costume}|{motion}|{facial}|{ambient}|{depth}"
    return f"{slug(costume, 24)}-{hashlib.sha1(raw.encode()).hexdigest()[:10]}"


def build_sprites(
    stage: Live2DStage, poses: dict[str, dict], out_dir: Path, quality: int, max_height: int
) -> dict[str, dict]:
    """Render each distinct pose once, centred, cropped to its alpha bounding box.

    The file is written at ``max_height`` rather than at stage resolution. A sprite
    rasterised against a 1080-tall stage is ~944px, but a 540px-wide card displays it
    around 264px, so shipping the full raster is ~13x the pixels anyone sees. The
    placement below is deliberately computed from the stage-space bbox and *not* from
    the resized file: it is a percentage of the stage, so it must not move when the
    stored resolution changes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    placed: dict[str, dict] = {}
    for i, (key, pose) in enumerate(sorted(poses.items()), 1):
        scale = LAYOUT_SCALE[pose["layout_mode"]] * depth_scale(pose["depth"])
        # centred horizontally: the per-side shift is applied in CSS, so the same crop
        # serves every position the pose appears at
        offset_y = -((0.5 + 0.3) - 0.5) * STAGE_H / (STAGE_H / 2)
        sprite = stage.render(pose["costume"], pose["motion"], pose["facial"], scale, offset_y, 0.0)
        if sprite is None:
            continue
        sprite = grade(sprite, pose["ambient"])
        bbox = sprite.getbbox()
        if not bbox:
            continue
        crop = sprite.crop(bbox)
        placed[key] = {
            "h": round(crop.height / STAGE_H * 100, 4),
            # placement as a percentage of the stage, so the page scales freely
            "left": round(bbox[0] / STAGE_W * 100, 4),
            "top": round(bbox[1] / STAGE_H * 100, 4),
            "w": round(crop.width / STAGE_W * 100, 4),
        }
        if max_height and crop.height > max_height:  # never upscale a small crop
            width = max(1, round(crop.width * max_height / crop.height))
            crop = crop.resize((width, max_height), Image.LANCZOS)
        crop.save(out_dir / f"{key}.webp", "WEBP", quality=quality, method=6)
        if i % 50 == 0:
            print(f"  {i}/{len(poses)} sprites")
    return placed


def spans_html(spans: list[tuple[str, bool]]) -> str:
    """Word runs as HTML, one ``<b>`` per *contiguous* run of changed words.

    Wrapping each word separately leaves the spaces between them outside the
    highlight, so a multi-word edit reads as a row of little boxes. Grouping first
    makes the highlight run across the whole edit, the way the rendered frames do.
    """
    out: list[str] = []
    for changed, group in groupby(spans, key=lambda s: s[1]):
        run = html.escape(" ".join(word for word, _ in group))
        out.append(f"<b>{run}</b>" if changed else run)
    return " ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument(
        "--out",
        default="web",
        help="Vite app root; sprites go to <out>/public/sprites, payload to <out>/src/data.json",
    )
    ap.add_argument("--kinds", default="text,speaker")
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument(
        "--sprite-height",
        type=int,
        default=560,
        help="max stored sprite height; ~2x the size a 540px card displays (0 = full)",
    )
    ap.add_argument(
        "--skip-sprites",
        action="store_true",
        help="reuse the rendered sprites and their placement from the existing payload",
    )
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    cmp_info = data["comparison"]
    new_ver = cmp_info["new_asset_version"]
    kinds = set(args.kinds.split(","))
    out_root = Path(args.out)
    sprites_dir = out_root / "public/sprites"
    data_file = out_root / "src/data.json"
    out_root.mkdir(parents=True, exist_ok=True)

    poses: dict[str, dict] = {}
    events: list[dict] = []
    dropped: list[dict] = []

    for event in data["events"]:
        bundle_name = event["bundle"].split("/")[1]
        scenarios = json.loads(
            Path("data/official", new_ver, event["bundle"].replace("/", "__") + ".json").read_text()
        )["scenarios"]
        episodes: list[dict] = []

        for ep in event["episodes"]:
            scenario = scenarios[ep["scenario_id"]]
            states = stage_states(scenario)
            scenes = scene_states(scenario)
            mode = "three_models" if scenario.get("FirstCharacterLayoutMode") == 1 else "normal"
            jp_path = Path("data/jp_assets") / bundle_name / f"{ep['scenario_id']}.json"
            jp_lines = (
                [(t.get("Body") or "").replace("\n", "") for t in json.loads(jp_path.read_text())["TalkData"]]
                if jp_path.exists()
                else []
            )
            frames: list[dict] = []

            for change in ep["changes"]:
                if change["kind"] not in kinds:
                    continue
                idx = change["talk_index_new"]
                if idx is None:
                    dropped.append({"episode_no": ep["episode_no"], "reason": "no talk index"})
                    continue
                state = scenes.get(idx) or {
                    "background": scenario.get("FirstBackground") or "",
                    "still": "",
                    "flashback": False,
                    "ambient": "normal",
                    "cover": "",
                }
                layers = []
                for char in states.get(idx, []):
                    if char["side"] in OFFSCREEN:
                        continue
                    key = sprite_key(
                        char["costume"], char["motion"], char["facial"], state["ambient"], char["depth"]
                    )
                    poses.setdefault(
                        key,
                        {
                            "ambient": state["ambient"],
                            "costume": char["costume"],
                            "depth": char["depth"],
                            "facial": char["facial"],
                            "layout_mode": mode,
                            "motion": char["motion"],
                        },
                    )
                    pos_x = POSITION_MAPS[mode].get(char["side"], (0.5, 0.5))[0]
                    pos_x += char.get("offset_x", 0.0) / STAGE_W
                    layers.append(
                        {
                            "depth": char["depth"],
                            # how far the pose sits from centre, in stage %
                            "dx": round((pos_x - 0.5) * 100, 4),
                            "key": key,
                            "speaking": char["speaking"],
                        }
                    )
                layers.sort(key=lambda c: (-c["depth"], c["speaking"]))

                spans_old, spans_new = diff_spans(change["old"], change["new"])
                frames.append(
                    {
                        "bg": state["background"],
                        "cover": state["cover"],
                        "flashback": state["flashback"],
                        "jp": jp_lines[idx] if idx < len(jp_lines) else "",
                        "layers": layers,
                        "new": spans_html(spans_new),
                        "old": spans_html(spans_old),
                        "speaker": change["speaker_new"] or change["speaker_old"] or "—",
                        "speakerOld": change["speaker_old"] or "",
                        "talkIndex": idx,
                    }
                )

            if frames:
                episodes.append(
                    {
                        "frames": frames,
                        "no": ep["episode_no"],
                        "slug": f"ep{ep['episode_no']:02d}",
                        "title": ep["title_en"],
                    }
                )

        if episodes:
            events.append(
                {
                    "changed": sum(len(e["frames"]) for e in episodes),
                    "episodes": episodes,
                    "id": event["event_id"],
                    "name": event["name_en"],
                    "nameJp": event["name_jp"],
                    "slug": f"event{event['event_id']:03d}",
                    "unit": event.get("unit", ""),
                }
            )

    total = sum(e["changed"] for e in events)
    print(f"{len(events)} event(s), {total} frames, {len(poses)} distinct poses to render")
    if args.skip_sprites:
        placed = json.loads(data_file.read_text())["sprites"]
        stale = [k for k in poses if k not in placed]
        if stale:
            raise SystemExit(
                f"--skip-sprites but {len(stale)} poses have no rendered sprite "
                f"(e.g. {stale[:3]}); rerun without it"
            )
        print(f"reusing {len(placed)} sprites")
    else:
        stage = Live2DStage(size=(STAGE_W, STAGE_H))
        placed = build_sprites(
            stage, poses, sprites_dir, args.quality, args.sprite_height
        )
    missing = [k for k in poses if k not in placed]

    payload = {
        "bgBase": BG_CDN,
        "comparison": cmp_info,
        "dropped": dropped,
        "events": events,
        "sprites": placed,
    }
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    sprite_bytes = sum(p.stat().st_size for p in sprites_dir.glob("*.webp"))
    data_bytes = data_file.stat().st_size
    print(f"\nsprites:     {len(placed)} files, {sprite_bytes / 1e6:.1f} MB")
    print(f"data.json:   {data_bytes / 1e6:.2f} MB")
    print(f"backgrounds: hot-linked from {BG_CDN} (0 bytes hosted)")
    print(f"TOTAL HOSTED: {(sprite_bytes + data_bytes) / 1e6:.1f} MB")
    print(f"\nnext: cd {out_root} && bun install && bun run build")
    if missing:
        print(f"  WARNING {len(missing)} poses produced no sprite: {missing[:5]}")
    if dropped:
        print(f"  dropped {len(dropped)} lines")


if __name__ == "__main__":
    main()
