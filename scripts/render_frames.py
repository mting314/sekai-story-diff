"""Render one before/after comparison frame per changed line.

Each frame rebuilds the on-screen context of the line from the official scenario
data — the background that is active at that ``TalkData`` index (walked out of the
snippet list) and the speaking character — then stacks the OLD line above the NEW
line in game-style dialogue boxes with the changed words highlighted.

Live2D poses cannot be rasterised outside the game, so the speaker is drawn from the
official character cutout art instead of the live model.

Output tree: ``data/images/<event>/<episode>/<index>_<speaker>.png``
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import unicodedata
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

JP_CDN = "https://storage.sekai.best/sekai-jp-assets"
MEDIA = Path("data/media")
MASTER = Path("data/master")

W, H = 1920, 1080

FONT_ROUND = "/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf"
FONT_BODY = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BODY_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_JP = "/System/Library/Fonts/Hiragino Sans GB.ttc"

INK = (34, 34, 51)
OLD_MARK = (196, 60, 60)
NEW_MARK = (28, 132, 92)

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"


# --- asset plumbing ----------------------------------------------------------


def cached(rel: str) -> Path | None:
    """Download ``rel`` off the JP asset mirror once, return the local path."""
    dest = MEDIA / rel
    if dest.exists():
        return dest if dest.stat().st_size else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = _session.get(f"{JP_CDN}/{rel}", timeout=60)
    except Exception:  # noqa: BLE001
        return None
    if resp.status_code != 200:
        dest.write_bytes(b"")
        return None
    dest.write_bytes(resp.content)
    return dest


def background_by_talk(scenario: dict) -> dict[int, str]:
    """Walk the snippet list → the background asset active at each talk index.

    ``SnippetAction.Talk = 1`` / ``SpecialEffect = 6``; within the effects,
    ``ChangeBackground = 7``. Anything else leaves the backdrop alone.
    """
    effects = scenario.get("SpecialEffectData") or []
    current = scenario.get("FirstBackground") or ""
    out: dict[int, str] = {}
    for snippet in scenario.get("Snippets") or []:
        action = snippet.get("Action")
        ref = snippet.get("ReferenceIndex", 0)
        if action == 6 and ref < len(effects):
            effect = effects[ref]
            if effect.get("EffectType") == 7 and effect.get("StringVal"):
                current = effect["StringVal"]
        elif action == 1:
            out[ref] = current
    return out


def portrait_bundles() -> dict[int, str]:
    """characterId → asset bundle of their 1★ card (the base school-uniform art)."""
    cards = json.loads((MASTER / "cards.json").read_text())
    best: dict[int, tuple[int, str]] = {}
    for card in cards:
        if card.get("cardRarityType") != "rarity_1":
            continue
        cid = card["characterId"]
        if cid not in best or card["id"] < best[cid][0]:
            best[cid] = (card["id"], card["assetbundleName"])
    return {cid: bundle for cid, (_, bundle) in best.items()}


def character_ids() -> dict[int, int]:
    """Character2dId → characterId."""
    rows = json.loads((MASTER / "character2ds.json").read_text())
    return {r["id"]: r["characterId"] for r in rows}


# --- drawing helpers ---------------------------------------------------------


def font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def cover(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def circle_portrait(img: Image.Image, size: int) -> Image.Image:
    face = cover(img.convert("RGB"), (size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    out = Image.new("RGBA", (size, size))
    out.paste(face, (0, 0), mask)
    return out


def diff_spans(old: str, new: str) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Word runs with a 'changed' flag, for highlighting."""
    # Exact word comparison — folding case here hides real edits such as
    # "have" → "HAVE" (emphasis) or "B-but" → "B-But".
    old_words, new_words = old.split(), new.split()
    matcher = difflib.SequenceMatcher(None, old_words, new_words)
    spans_old: list[tuple[str, bool]] = []
    spans_new: list[tuple[str, bool]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        changed = tag != "equal"
        for word in old_words[i1:i2]:
            spans_old.append((word, changed))
        for word in new_words[j1:j2]:
            spans_new.append((word, changed))
    return spans_old, spans_new


def wrap_spans(
    spans: list[tuple[str, bool]], fnt: ImageFont.FreeTypeFont, max_width: int
) -> list[list[tuple[str, bool]]]:
    lines: list[list[tuple[str, bool]]] = [[]]
    width = 0.0
    space = fnt.getlength(" ")
    for word, changed in spans:
        word_w = fnt.getlength(word)
        if lines[-1] and width + space + word_w > max_width:
            lines.append([])
            width = 0.0
        if lines[-1]:
            width += space
        lines[-1].append((word, changed))
        width += word_w
    return lines


def draw_spans(
    canvas: Image.Image,
    lines: list[list[tuple[str, bool]]],
    origin: tuple[int, int],
    fnt: ImageFont.FreeTypeFont,
    bold: ImageFont.FreeTypeFont,
    leading: int,
    base_color: tuple[int, int, int],
    mark_color: tuple[int, int, int],
) -> int:
    """Draw wrapped words; changed ones get a tinted wash + bold, coloured text.

    The wash goes on its own layer — ``ImageDraw`` fills do not alpha-blend
    reliably onto an already-composited canvas, which paints solid blocks over
    the very words we want readable.
    """
    wash = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    wash_draw = ImageDraw.Draw(wash)
    x0, y = origin
    positions: list[tuple[float, int, str, bool]] = []
    for line in lines:
        x = float(x0)
        for word, changed in line:
            width = (bold if changed else fnt).getlength(word)
            if changed:
                wash_draw.rounded_rectangle(
                    (x - 6, y - 4, x + width + 6, y + fnt.size + 10),
                    radius=8,
                    fill=(*mark_color, 34),
                )
            positions.append((x, y, word, changed))
            x += width + fnt.getlength(" ")
        y += leading
    canvas.alpha_composite(wash)
    draw = ImageDraw.Draw(canvas)
    for x, ty, word, changed in positions:
        draw.text(
            (x, ty),
            word,
            font=bold if changed else fnt,
            fill=mark_color if changed else base_color,
        )
    return y


BOX_LEFT, BOX_RIGHT = 130, W - 130
BOX_INNER = BOX_RIGHT - BOX_LEFT - 130


def layout_text(spans: list[tuple[str, bool]]) -> tuple:
    """Pick a font size that keeps the line inside a sane box, and wrap it."""
    for size, leading in ((42, 58), (38, 53), (34, 48)):
        body_font = font(FONT_BODY, size)
        lines = wrap_spans(spans, body_font, BOX_INNER)
        if len(lines) <= 3:
            break
    return body_font, font(FONT_BODY_BOLD, size), lines, leading


def box_height(lines: list) -> int:
    return max(150, 96 + len(lines) * 58)


def dialogue_box(
    canvas: Image.Image,
    top: int,
    layout: tuple,
    label: str,
    label_color: tuple[int, int, int],
    speaker: str,
    mark_color: tuple[int, int, int],
) -> int:
    """One game-style dialogue window with a BEFORE/AFTER tag; returns its height."""
    body_font, bold_font, lines, leading = layout
    left, right = BOX_LEFT, BOX_RIGHT
    height = box_height(lines)
    box = Image.new("RGBA", (right - left, height), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle(
        (0, 0, right - left - 1, height - 1), radius=46, fill=(255, 255, 255, 235)
    )
    canvas.alpha_composite(box, (left, top))

    name_font = font(FONT_ROUND, 34)
    label_font = font(FONT_ROUND, 25)
    draw = ImageDraw.Draw(canvas)
    # name plate
    plate_w = int(name_font.getlength(speaker)) + 74
    draw.rounded_rectangle(
        (left + 34, top - 30, left + 34 + plate_w, top + 30), radius=30, fill=(93, 88, 130)
    )
    draw.ellipse((left + 52, top - 8, left + 68, top + 8), fill=(112, 222, 219))
    draw.text((left + 78, top - 20), speaker, font=name_font, fill=(255, 255, 255))

    # before/after tag, next to the name plate so it never sits under the portrait
    tag_x = left + 54 + plate_w
    tag_w = int(label_font.getlength(label)) + 34
    draw.rounded_rectangle((tag_x, top - 27, tag_x + tag_w, top + 27), radius=26, fill=label_color)
    draw.text((tag_x + 17, top - 16), label, font=label_font, fill=(255, 255, 255))

    draw_spans(canvas, lines, (left + 62, top + 58), body_font, bold_font, leading, INK, mark_color)
    return height


def slug(text: str, limit: int = 46) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()
    return text[:limit] or "untitled"


def render_frame(
    out_path: Path,
    bg_path: Path | None,
    portrait_path: Path | None,
    header: str,
    subheader: str,
    speaker: str,
    old: str,
    new: str,
    jp: str,
    versions: tuple[str, str],
    scene: Image.Image | None = None,
) -> None:
    """``scene`` overrides the backdrop with a pre-composed frame (Live2D mode)."""
    if scene is not None:
        canvas = cover(scene.convert("RGB"), (W, H)).convert("RGBA")
    elif bg_path and bg_path.exists():
        canvas = cover(Image.open(bg_path).convert("RGB"), (W, H)).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (W, H), (38, 34, 58, 255))
    canvas.alpha_composite(Image.new("RGBA", (W, H), (18, 16, 34, 92)))

    if portrait_path and portrait_path.exists():
        size = 250
        portrait = circle_portrait(Image.open(portrait_path), size)
        shadow = Image.new("RGBA", (size + 40, size + 40), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((20, 20, size + 19, size + 19), fill=(0, 0, 0, 120))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))
        canvas.alpha_composite(shadow, (W - size - 130, 34))
        canvas.alpha_composite(portrait, (W - size - 110, 36))

    header_bar = Image.new("RGBA", (1180, 190), (0, 0, 0, 0))
    ImageDraw.Draw(header_bar).rounded_rectangle((0, 0, 1179, 189), radius=34, fill=(24, 20, 44, 210))
    canvas.alpha_composite(header_bar, (0, -40))
    draw = ImageDraw.Draw(canvas)
    draw.text((60, 34), header, font=font(FONT_ROUND, 40), fill=(255, 255, 255))
    draw.text((60, 90), subheader, font=font(FONT_BODY, 30), fill=(198, 195, 225))

    spans_old, spans_new = diff_spans(old, new)
    layout_old, layout_new = layout_text(spans_old), layout_text(spans_new)
    # bottom-anchor the pair so the scene stays visible above them
    gap = 86
    bottom = H - 120
    top_new = bottom - box_height(layout_new[2])
    top_old = top_new - gap - box_height(layout_old[2])
    dialogue_box(
        canvas, top_old, layout_old, f"BEFORE  {versions[0]}", (176, 68, 68), speaker, OLD_MARK
    )
    dialogue_box(
        canvas, top_new, layout_new, f"AFTER  {versions[1]}", (46, 128, 96), speaker, NEW_MARK
    )

    if jp:
        jp_font = font(FONT_JP, 28)
        draw.text((150, 1010), f"JP  {jp}", font=jp_font, fill=(226, 224, 245))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(out_path, quality=92)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument("--out", default="data/images")
    ap.add_argument("--limit", type=int, default=0, help="render at most N frames (debug)")
    ap.add_argument("--kinds", default="text,speaker", help="change kinds to render")
    args = ap.parse_args()

    data = json.loads(Path(args.changes).read_text())
    old_ver = data["comparison"]["old_asset_version"]
    new_ver = data["comparison"]["new_asset_version"]
    kinds = set(args.kinds.split(","))

    c2d = character_ids()
    bundles = portrait_bundles()
    jp_cache: dict[str, list[str]] = {}
    rendered = 0
    index: list[dict] = []

    for event in data["events"]:
        event_dir = Path(args.out) / f"event_{event['event_id']:03d}_{slug(event['name_en'])}"
        bundle_name = event["bundle"].split("/")[1]
        for ep in event["episodes"]:
            scenario_path = (
                Path("data/official") / new_ver / (event["bundle"].replace("/", "__") + ".json")
            )
            scenario = json.loads(scenario_path.read_text())["scenarios"][ep["scenario_id"]]
            bg_map = background_by_talk(scenario)
            talks = scenario.get("TalkData") or []

            jp_path = Path("data/jp_assets") / bundle_name / f"{ep['scenario_id']}.json"
            if ep["scenario_id"] not in jp_cache and jp_path.exists():
                jp_cache[ep["scenario_id"]] = [
                    (t.get("Body") or "").replace("\n", "")
                    for t in json.loads(jp_path.read_text()).get("TalkData", [])
                ]

            ep_dir = event_dir / f"ep{ep['episode_no']:02d}_{slug(ep['title_en'])}"
            for change in ep["changes"]:
                if change["kind"] not in kinds:
                    continue
                idx = change["talk_index_new"]
                if idx is None:
                    continue
                talk = talks[idx] if idx < len(talks) else {}
                bg_name = bg_map.get(idx, scenario.get("FirstBackground") or "")
                bg_path = cached(f"scenario/background/{bg_name}/{bg_name}.webp") if bg_name else None

                portrait_path = None
                chars = talk.get("TalkCharacters") or []
                c2d_id = chars[0].get("Character2dId") if chars else None
                cid = c2d.get(c2d_id or -1)
                if cid and cid in bundles:
                    portrait_path = cached(
                        f"character/member_cutout/{bundles[cid]}/normal.webp"
                    )

                speaker = change["speaker_new"] or change["speaker_old"] or "—"
                jp_line = ""
                lines_jp = jp_cache.get(ep["scenario_id"], [])
                if idx < len(lines_jp):
                    jp_line = lines_jp[idx]

                out_path = ep_dir / f"{idx:03d}_{slug(speaker, 18)}.jpg"
                render_frame(
                    out_path,
                    bg_path,
                    portrait_path,
                    event["name_en"],
                    f"Episode {ep['episode_no']} - {ep['title_en']}   |   line #{idx}",
                    speaker,
                    change["old"],
                    change["new"],
                    jp_line,
                    (old_ver, new_ver),
                )
                index.append(
                    {
                        "path": str(out_path),
                        "event_id": event["event_id"],
                        "episode_no": ep["episode_no"],
                        "talk_index": idx,
                        "speaker": speaker,
                    }
                )
                rendered += 1
                if rendered % 25 == 0:
                    print(f"  {rendered} frames")
                if args.limit and rendered >= args.limit:
                    print(f"stopped at --limit {args.limit}")
                    Path(args.out, "index.json").write_text(json.dumps(index, indent=1))
                    return
    Path(args.out).mkdir(parents=True, exist_ok=True)
    Path(args.out, "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"rendered {rendered} frames into {args.out}")


if __name__ == "__main__":
    main()
