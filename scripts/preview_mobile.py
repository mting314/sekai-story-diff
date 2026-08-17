"""Render what a frame looks like at a given CSS viewport width, without a browser.

No headless browser is available here, so this reimplements the site's stage/box
geometry in Pillow: same percentage placement, same clamp() sizes, same 16:9 stage.
It is a check on the CSS, not a replacement for it — if the numbers here look wrong,
the numbers in style.css are wrong too.

    $P scripts/preview_mobile.py --width 390 --line 4:9
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
from render_frames import FONT_BODY, FONT_BODY_BOLD, FONT_ROUND, cached, cover, font  # noqa: E402

DPR = 3  # render at phone pixel density so the preview is judged the way a phone shows it


def clamp(lo: float, val: float, hi: float) -> float:
    return max(lo, min(val, hi))


def draw_frame(data: dict, frame: dict, css_width: int, old: bool, versions: tuple[str, str]):
    """One panel at ``css_width`` CSS pixels, rendered at DPR."""
    w = css_width * DPR
    h = round(w * 9 / 16)
    stage_cqw = css_width / 100  # 1cqw in CSS px

    bg_name = frame["bg"]
    bg_path = Path("web/public/bg") / f"{bg_name}.webp"
    canvas = (
        cover(Image.open(bg_path).convert("RGB"), (w, h))
        if bg_path.exists()
        else Image.new("RGB", (w, h), (20, 18, 32))
    ).convert("RGBA")

    for layer in frame["layers"]:
        spec = data["sprites"].get(layer["key"])
        if not spec:
            continue
        sprite = Image.open(Path("web/public/sprites") / f"{layer['key']}.webp").convert("RGBA")
        sw = round(spec["w"] / 100 * w)
        sh = round(spec["h"] / 100 * h)
        sx = round((spec["left"] + layer["dx"]) / 100 * w)
        sy = round(spec["top"] / 100 * h)
        canvas.alpha_composite(sprite.resize((sw, sh), Image.LANCZOS), (sx, sy))
    if frame["flashback"]:
        canvas.alpha_composite(Image.new("RGBA", canvas.size, (0, 0, 0, 77)))

    # --- the dialogue box, mirroring the clamp() values in style.css ---
    px = lambda v: round(v * DPR)  # noqa: E731 - CSS px -> device px
    body_size = clamp(10.5, 2.4 * stage_cqw, 17)
    plate_size = clamp(9.5, 2.1 * stage_cqw, 15)
    tag_size = clamp(9, 1.95 * stage_cqw, 14)
    pad_x = clamp(9, 2.7 * stage_cqw, 19)
    pad_top = clamp(5, 1.6 * stage_cqw, 11)
    pad_bot = clamp(6, 1.9 * stage_cqw, 13)
    radius = clamp(9, 2.9 * stage_cqw, 20)
    side = 0.035 if css_width < 700 else 0.05
    bottom = 0.04 if css_width < 700 else 0.05

    body = font(FONT_BODY, px(body_size))
    bold = font(FONT_BODY_BOLD, px(body_size))
    plate_font = font(FONT_ROUND, px(plate_size))
    tag_font = font(FONT_ROUND, px(tag_size))

    left, right = round(w * side), round(w * (1 - side))
    inner = right - left - 2 * px(pad_x)

    import re

    words: list[tuple[str, bool]] = []
    for chunk in re.split(r"(<b>.*?</b>)", frame["old"] if old else frame["new"]):
        if not chunk:
            continue
        changed = chunk.startswith("<b>")
        text = re.sub(r"</?b>", "", chunk)
        text = text.replace("&#x27;", "'").replace("&amp;", "&").replace("&quot;", '"')
        words += [(word, changed) for word in text.split()]

    lines: list[list[tuple[str, bool]]] = [[]]
    width_used = 0.0
    space = body.getlength(" ")
    for word, changed in words:
        ww = (bold if changed else body).getlength(word)
        if lines[-1] and width_used + space + ww > inner:
            lines.append([])
            width_used = 0.0
        if lines[-1]:
            width_used += space
        lines[-1].append((word, changed))
        width_used += ww

    leading = px(body_size * 1.38)
    plate_h = px(plate_size * 1.9)
    box_h = px(pad_top) + plate_h + len(lines) * leading + px(pad_bot)
    top = h - round(h * bottom) - box_h

    box = Image.new("RGBA", (right - left, box_h), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle(
        (0, 0, right - left - 1, box_h - 1), radius=px(radius), fill=(255, 255, 255, 240)
    )
    canvas.alpha_composite(box, (left, top))

    draw = ImageDraw.Draw(canvas)
    x = left + px(pad_x)
    y = top + px(pad_top)
    name = frame["speakerOld"] if old and frame["speakerOld"] else frame["speaker"]
    pw = plate_font.getlength(name) + px(plate_size * 1.7)
    draw.rounded_rectangle(
        (x, y, x + pw, y + px(plate_size * 1.55)), radius=px(plate_size), fill=(93, 88, 130)
    )
    draw.text((x + px(plate_size * 0.85), y + px(plate_size * 0.2)), name, font=plate_font, fill=(255, 255, 255))

    label = f"{'BEFORE ' + versions[0] if old else 'AFTER ' + versions[1]}"
    tx = x + pw + px(4)
    tw = tag_font.getlength(label) + px(tag_size * 1.5)
    draw.rounded_rectangle(
        (tx, y, tx + tw, y + px(plate_size * 1.55)),
        radius=px(tag_size),
        fill=(176, 68, 68) if old else (46, 128, 96),
    )
    draw.text((tx + px(tag_size * 0.75), y + px(tag_size * 0.28)), label, font=tag_font, fill=(255, 255, 255))

    ty = y + plate_h
    for line in lines:
        lx = float(x)
        for word, changed in line:
            fnt = bold if changed else body
            ww = fnt.getlength(word)
            if changed:
                wash = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
                ImageDraw.Draw(wash).rounded_rectangle(
                    (lx - px(2), ty - px(1), lx + ww + px(2), ty + px(body_size * 1.2)),
                    radius=px(3),
                    fill=(196, 60, 60, 46) if old else (28, 132, 92, 46),
                )
                canvas.alpha_composite(wash)
            draw.text((lx, ty), word, font=fnt, fill=(165, 47, 47) if changed and old else (18, 107, 72) if changed else (34, 34, 51))
            lx += ww + space
        ty += leading

    return canvas.convert("RGB"), body_size, len(lines), box_h / h


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--width", type=int, nargs="+", default=[390])
    ap.add_argument("--line", default="", help="episode:talkIndex, default = the longest line")
    ap.add_argument("--out", default="/tmp/mobile_preview.png")
    args = ap.parse_args()

    data = json.loads(Path("web/src/data.json").read_text())
    ev = data["events"][0]
    frames = [(ep, f) for ep in ev["episodes"] for f in ep["frames"]]
    if args.line:
        e, i = args.line.split(":")
        chosen = next(f for ep, f in frames if ep["no"] == int(e) and f["talkIndex"] == int(i))
    else:  # worst case: the longest line that also has characters on stage
        chosen = max((f for _, f in frames if f["layers"]), key=lambda f: len(f["old"]))

    versions = (data["comparison"]["old_asset_version"], data["comparison"]["new_asset_version"])
    panels = []
    for width in args.width:
        for old in (True, False):
            img, size, lines, frac = draw_frame(data, chosen, width, old, versions)
            panels.append((f"{width}px CSS  ·  text {size:.1f}px  ·  {lines} lines  ·  box {frac:.0%} of frame", img))
            if old:
                print(f"  {width}px: text {size:.1f}px, {lines} lines, box covers {frac:.0%} of the frame")

    pad = 18
    label_h = 34
    W = max(p[1].width for p in panels) + pad * 2
    H = sum(p[1].height + label_h for p in panels) + pad * (len(panels) + 1)
    sheet = Image.new("RGB", (W, H), (20, 18, 32))
    d = ImageDraw.Draw(sheet)
    y = pad
    for label, img in panels:
        d.text((pad, y), label, font=font(FONT_BODY, 20), fill=(200, 196, 226))
        sheet.paste(img, (pad, y + label_h))
        y += img.height + label_h + pad
    sheet.save(args.out)
    print(f"wrote {args.out} ({sheet.width}x{sheet.height})")


if __name__ == "__main__":
    main()
