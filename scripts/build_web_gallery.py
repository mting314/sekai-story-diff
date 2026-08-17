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

import requests
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
    unresolved_motion_bases,
)
from render_frames import cached, diff_spans, slug  # noqa: E402
from report import jp_lines as jp_source  # noqa: E402

_banner_session = requests.Session()
_banner_session.headers["User-Agent"] = "sekai-story-diff"

STAGE_W, STAGE_H = 1920, 1080
# Backgrounds are served from our own build, not hot-linked. storage.sekai.best
# returns 403 for a cross-site Referer — it allows its own pages and referer-less
# requests only — and defeating that with a no-referrer policy would be helping
# ourselves to someone else's bandwidth against their stated wishes. All 17 come to
# about 1 MB at display resolution, so there is nothing to gain by arguing.
BG_WIDTH = 1100  # ~2x what a 540px card shows
BANNER_WIDTH = 640
INDEXER = Path.home() / "github/sekai-story-indexer/events_index.json"
# Events the mirror shows as re-uploaded on their own dates, awaiting a diff.
PENDING_EVENTS = [24, 31, 74, 75, 111, 155]
# Unit identity. The indexer names units after the group (leo_need); the game's own
# master data names them after the asset family (light_sound), which is what the logo
# files are keyed by. "mixed" events front several units and get no single logo.
UNITS = {
    "leo_need": ("light_sound", "#4a63e7"),
    "more_more_jump": ("idol", "#44c266"),
    "vivid_bad_squad": ("street", "#ee1166"),
    "wonderlands_showtime": ("theme_park", "#ff9900"),
    "nightcord": ("school_refusal", "#8b62c4"),
    "virtual_singer": ("piapro", "#00bcd4"),
    "mixed": ("", "#8f89b5"),
}


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


def build_backgrounds(names: set[str], out_dir: Path, width: int, quality: int) -> int:
    """Copy each background into the site at display resolution. Returns bytes written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in sorted(names):
        if not name:
            continue
        src = cached(f"scenario/background/{name}/{name}.webp")
        if not src:
            print(f"  WARNING background {name} unavailable")
            continue
        image = Image.open(src).convert("RGB")
        if image.width > width:
            image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
        dest = out_dir / f"{name}.webp"
        image.save(dest, "WEBP", quality=quality, method=6)
        total += dest.stat().st_size
    return total


def event_meta() -> dict[int, dict]:
    """Event id -> display metadata, merged from the indexer and the EN master data.

    The indexer carries the unit and the banner art; the EN master carries the English
    name. Neither has both.
    """
    out: dict[int, dict] = {}
    if INDEXER.exists():
        for row in json.loads(INDEXER.read_text()):
            out[row["event_id"]] = {
                "banner": row.get("banner_url", ""),
                "nameJp": row.get("name", ""),
                "unit": row.get("unit", ""),
            }
    en_path = Path("data/master/events_en.json")
    if en_path.exists():
        for row in json.loads(en_path.read_text()):
            entry = out.setdefault(row["id"], {"banner": "", "nameJp": "", "unit": ""})
            entry["name"] = row.get("name", "")
            entry["bundle"] = row.get("assetbundleName", "")
    return out


def fetch_banner(url: str, dest: Path, width: int, quality: int) -> bool:
    """Self-host the banner. The mirror 403s a cross-site Referer, same as backgrounds."""
    if not url or dest.exists():
        return dest.exists()
    try:
        resp = _banner_session.get(url, timeout=60)
    except Exception:  # noqa: BLE001
        return False
    if resp.status_code != 200:
        return False
    import io

    image = Image.open(io.BytesIO(resp.content)).convert("RGB")
    if image.width > width:
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, "WEBP", quality=quality, method=6)
    return True


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
    ap.add_argument(
        "--changes",
        nargs="+",
        default=["data/official_changes.json", "data/official_changes_*.json"],
        help="one or more diff payloads (globs allowed); each carries its own version pair",
    )
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

    import glob as _glob

    paths = sorted({q for pattern in args.changes for q in _glob.glob(pattern)})
    if not paths:
        raise SystemExit(f"no diff payloads matched {args.changes}")
    payloads = [json.loads(Path(q).read_text()) for q in paths]
    print(f"merging {len(payloads)} diff payload(s):")
    for q, d in zip(paths, payloads):
        c = d["comparison"]
        print(f"  {Path(q).name}: {c['old_asset_version']} -> {c['new_asset_version']}"
              f" ({len(d['events'])} event(s))")
    kinds = set(args.kinds.split(","))
    out_root = Path(args.out)
    sprites_dir = out_root / "public/sprites"
    data_file = out_root / "src/data.json"
    out_root.mkdir(parents=True, exist_ok=True)

    poses: dict[str, dict] = {}
    events: list[dict] = []
    dropped: list[dict] = []
    metas = event_meta()

    # flatten to (version pair, event) so each event keeps its own bracket: the six
    # later events were each re-uploaded on their own date, so there is no single
    # before/after for the site as a whole
    for cmp_info, event in [(d["comparison"], e) for d in payloads for e in d["events"]]:
        new_ver = cmp_info["new_asset_version"]
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
            # report.py owns the JP fetch + cache; reuse it so there is one implementation
            jp_lines = jp_source(bundle_name, ep["scenario_id"])
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
            meta = metas.get(event["event_id"], {})
            unit = meta.get("unit") or ""
            logo, colour = UNITS.get(unit, ("", "#8f89b5"))
            bundle = meta.get("bundle") or bundle_name
            banner = f"event/{bundle}.webp" if fetch_banner(
                meta.get("banner", ""), out_root / "public/event" / f"{bundle}.webp",
                BANNER_WIDTH, args.quality
            ) else ""
            events.append(
                {
                    "banner": banner,
                    "newReleasedAt": cmp_info.get("new_released_at", ""),
                    "newVersion": cmp_info["new_asset_version"],
                    "oldReleasedAt": cmp_info.get("old_released_at", ""),
                    "oldVersion": cmp_info["old_asset_version"],
                    "changed": sum(len(e["frames"]) for e in episodes),
                    "colour": colour,
                    "episodes": episodes,
                    "id": event["event_id"],
                    "name": event["name_en"],
                    "nameJp": meta.get("nameJp") or event["name_jp"],
                    "slug": f"event{event['event_id']:03d}",
                    "unit": unit,
                    "unitLogo": f"unit/{logo}.png" if logo else "",
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

    bg_bytes = build_backgrounds(
        {f["bg"] for e in events for ep in e["episodes"] for f in ep["frames"]},
        out_root / "public/bg",
        BG_WIDTH,
        args.quality,
    )

    diffed = {e["id"] for e in events}
    pending = []
    for event_id in [i for i in PENDING_EVENTS if i not in diffed]:
        meta = metas.get(event_id, {})
        unit = meta.get("unit") or ""
        logo, colour = UNITS.get(unit, ("", "#8f89b5"))
        bundle = meta.get("bundle") or ""
        banner = f"event/{bundle}.webp" if bundle and fetch_banner(
            meta.get("banner", ""), out_root / "public/event" / f"{bundle}.webp",
            BANNER_WIDTH, args.quality
        ) else ""
        pending.append(
            {
                "banner": banner,
                "colour": colour,
                "id": event_id,
                "name": meta.get("name", ""),
                "nameJp": meta.get("nameJp", ""),
                "unit": unit,
                "unitLogo": f"unit/{logo}.png" if logo else "",
            }
        )

    payload = {
        "comparison": {
            "new_asset_version": max(e["newVersion"] for e in events),
            "old_asset_version": min(e["oldVersion"] for e in events),
            "pairs": sorted({(e["oldVersion"], e["newVersion"]) for e in events}),
            "region": "en",
        },
        "dropped": dropped,
        "events": events,
        "pending": pending,
        "sprites": placed,
    }
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    sprite_bytes = sum(p.stat().st_size for p in sprites_dir.glob("*.webp"))
    data_bytes = data_file.stat().st_size
    print(f"\nsprites:     {len(placed)} files, {sprite_bytes / 1e6:.1f} MB")
    print(f"data.json:   {data_bytes / 1e6:.2f} MB")
    banner_bytes = sum(p.stat().st_size for p in (out_root / "public/event").glob("*.webp"))
    print(f"backgrounds: {bg_bytes / 1e6:.1f} MB at {BG_WIDTH}px (self-hosted)")
    print(f"banners:     {banner_bytes / 1e6:.2f} MB for {len(events) + len(pending)} events")
    print(f"TOTAL HOSTED: {(sprite_bytes + data_bytes + bg_bytes) / 1e6:.1f} MB")
    print(f"\nnext: cd {out_root} && bun install && bun run build")
    if missing:
        print(f"  WARNING {len(missing)} poses produced no sprite: {missing[:5]}")
    if unresolved_motion_bases:
        # no motion set on the mirror, so these render in the model's rest pose
        print(f"  WARNING {len(unresolved_motion_bases)} costumes have no motion base and "
              f"render as a T-pose: {sorted(unresolved_motion_bases)}")
    if dropped:
        print(f"  dropped {len(dropped)} lines")


if __name__ == "__main__":
    main()
