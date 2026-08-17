"""Build the gallery as a static site that composes each frame in the browser.

The baked gallery ships 359 full-HD JPEGs (~193 MB) that each contain the background
twice and the dialogue text as pixels. Almost none of that has to be hosted:

* backgrounds are already on the public asset mirror — hot-link them
* the dialogue box, text and the Japanese source line are HTML, so they cost nothing,
  stay selectable and stay searchable
* only the posed characters are ours, and they dedupe hard: the sprite art depends on
  (costume, motion, facial, grade) but *not* on which side of the stage it sits, so one
  crop serves every line reusing the pose, positioned with CSS

The result is small enough to publish on GitHub Pages as-is — no build step, all paths
relative. What is emitted::

    data/gallery_web/sprites/<key>.webp   cropped, alpha, one per distinct pose
    data/gallery_web/data.json            events → episodes → frames, sprite placement
    data/gallery_web/index.html           renders it, lazily

Run after the diff exists::

    $P scripts/build_web_gallery.py
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path

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
    stage: Live2DStage, poses: dict[str, dict], out_dir: Path, quality: int
) -> dict[str, dict]:
    """Render each distinct pose once, centred, cropped to its alpha bounding box."""
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
        crop.save(out_dir / f"{key}.webp", "WEBP", quality=quality, method=6)
        placed[key] = {
            "h": round(crop.height / STAGE_H * 100, 4),
            # placement as a percentage of the stage, so the page scales freely
            "left": round(bbox[0] / STAGE_W * 100, 4),
            "top": round(bbox[1] / STAGE_H * 100, 4),
            "w": round(crop.width / STAGE_W * 100, 4),
        }
        if i % 50 == 0:
            print(f"  {i}/{len(poses)} sprites")
    return placed


def spans_html(spans: list[tuple[str, bool]]) -> str:
    return " ".join(
        f"<b>{html.escape(w)}</b>" if changed else html.escape(w) for w, changed in spans
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--changes", default="data/official_changes.json")
    ap.add_argument("--out", default="data/gallery_web")
    ap.add_argument("--kinds", default="text,speaker")
    ap.add_argument("--quality", type=int, default=88)
    ap.add_argument(
        "--html-only",
        action="store_true",
        help="rewrite index.html against the existing sprites and data.json",
    )
    args = ap.parse_args()

    if args.html_only:
        out = Path(args.out)
        (out / "index.html").write_text(PAGE, encoding="utf-8")
        print(f"wrote {out / 'index.html'} ({len(PAGE) / 1024:.0f} KB), sprites untouched")
        return

    data = json.loads(Path(args.changes).read_text())
    cmp_info = data["comparison"]
    new_ver = cmp_info["new_asset_version"]
    kinds = set(args.kinds.split(","))
    out_root = Path(args.out)
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
    stage = Live2DStage(size=(STAGE_W, STAGE_H))
    placed = build_sprites(stage, poses, out_root / "sprites", args.quality)
    missing = [k for k in poses if k not in placed]

    payload = {
        "bgBase": BG_CDN,
        "comparison": cmp_info,
        "dropped": dropped,
        "events": events,
        "sprites": placed,
    }
    (out_root / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (out_root / "index.html").write_text(PAGE, encoding="utf-8")
    # GitHub Pages runs Jekyll by default, which skips files and dirs beginning with _
    (out_root / ".nojekyll").write_text("", encoding="utf-8")

    sprite_bytes = sum(p.stat().st_size for p in (out_root / "sprites").glob("*.webp"))
    data_bytes = (out_root / "data.json").stat().st_size
    print(f"\nsprites:     {len(placed)} files, {sprite_bytes / 1e6:.1f} MB")
    print(f"data.json:   {data_bytes / 1e6:.2f} MB")
    print(f"backgrounds: hot-linked from {BG_CDN} (0 bytes hosted)")
    print(f"TOTAL HOSTED: {(sprite_bytes + data_bytes) / 1e6:.1f} MB")
    if missing:
        print(f"  WARNING {len(missing)} poses produced no sprite: {missing[:5]}")
    if dropped:
        print(f"  dropped {len(dropped)} lines")


PAGE = """<!doctype html>
<html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Sekai EN — official retranslation, line by line</title>
<style>
 :root { color-scheme: dark; --bg:#14121f; --panel:#1c1930; --line:#2c2843;
         --dim:#a9a4c6; --accent:#7c6bd6; }
 * { box-sizing:border-box; }
 body { margin:0; background:var(--bg); color:#eceaf6;
        font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
 a { color:inherit; text-decoration:none; }
 mark { background:#7c6bd655; color:inherit; border-radius:3px; }

 /* ---- drawer ---- */
 #burger { position:fixed; top:14px; left:14px; z-index:30; width:42px; height:42px;
           border:0; border-radius:12px; background:#272247; color:#fff; cursor:pointer;
           font-size:18px; box-shadow:0 4px 16px #0008; }
 #burger:hover { background:#332c5c; }
 #burger[hidden] { display:none; }
 #drawer { position:fixed; z-index:29; inset:0 auto 0 0; width:310px; background:#171429;
           border-right:1px solid var(--line); overflow-y:auto; padding:66px 0 30px;
           transform:translateX(-100%); transition:transform .18s ease; }
 #drawer.open { transform:none; }
 #scrim { position:fixed; inset:0; z-index:28; background:#0009; display:none; }
 #scrim.open { display:block; }
 .nav-h { padding:12px 20px 5px; font-size:11px; letter-spacing:.09em;
          text-transform:uppercase; color:#7d77a5; }
 .nav-ev { display:block; padding:8px 20px; border-left:3px solid transparent; }
 .nav-ev:hover { background:#221d3d; }
 .nav-ev.on { background:#221d3d; border-left-color:var(--accent); }
 .nav-ev small { color:var(--dim); display:block; font-size:12px; }
 .nav-ev.soon { opacity:.4; }
 .nav-ep { display:flex; justify-content:space-between; gap:10px;
           padding:6px 20px 6px 30px; font-size:13.5px; color:#d7d3ee; }
 .nav-ep:hover { background:#221d3d; }
 .nav-ep i { color:#7d77a5; font-style:normal; }

 /* ---- home ---- */
 .home { max-width:1100px; margin:0 auto; padding:70px 24px 60px; }
 .hero h1 { margin:0 0 8px; font-size:32px; letter-spacing:-.01em; }
 .hero p { margin:0; color:var(--dim); max-width:70ch; }
 .vers { display:inline-block; margin-top:14px; padding:5px 12px; border-radius:10px;
         background:#221d3d; font-size:13px; }
 .vers b { color:#c9bfff; }
 #q { width:100%; margin:26px 0 6px; padding:14px 16px; font-size:16px; color:#fff;
      background:var(--panel); border:1px solid var(--line); border-radius:12px; }
 #q:focus { outline:2px solid var(--accent); }
 .hint { color:#7d77a5; font-size:12.5px; }
 .cards { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr));
          gap:16px; margin-top:22px; }
 .card { display:block; background:var(--panel); border:1px solid var(--line);
         border-radius:14px; padding:16px 18px; transition:border-color .12s; }
 .card:hover { border-color:var(--accent); }
 .card.soon { opacity:.45; }
 .card h3 { margin:0 0 2px; font-size:17px; }
 .card .jp { color:var(--dim); font-size:13px; }
 .card .row { margin-top:10px; display:flex; gap:8px; flex-wrap:wrap; }
 .pill { background:#2a2450; border-radius:20px; padding:2px 10px; font-size:12px; }
 .pill.hot { background:#5a3550; color:#ffc9df; }
 .sec { margin:34px 0 10px; font-size:13px; text-transform:uppercase;
        letter-spacing:.09em; color:#7d77a5; }
 .hit { display:block; background:var(--panel); border-radius:11px; padding:10px 14px;
        margin-bottom:8px; border-left:3px solid var(--accent); }
 .hit .who { font-size:12px; color:var(--dim); }
 .hit .o { color:#d78d8d; } .hit .n { color:#8fdcb6; }

 /* ---- event view ---- */
 .topbar { position:sticky; top:0; z-index:20; background:#14121feb;
           backdrop-filter:blur(8px); border-bottom:1px solid var(--line);
           padding:12px 24px 12px 68px; display:flex; align-items:center;
           gap:14px; flex-wrap:wrap; }
 .topbar h2 { margin:0; font-size:17px; }
 .topbar .meta { color:var(--dim); font-size:12.5px; }
 #filter { margin-left:auto; padding:7px 12px; min-width:220px; color:#fff;
           background:var(--panel); border:1px solid var(--line); border-radius:9px; }
 details { margin:0 24px; border-top:1px solid var(--line); }
 summary { cursor:pointer; padding:15px 4px; font-size:18px; font-weight:600;
           display:flex; align-items:center; gap:10px; scroll-margin-top:64px; }
 summary::-webkit-details-marker { display:none; }
 summary::before { content:"▸"; color:var(--accent); transition:transform .15s; }
 details[open] summary::before { transform:rotate(90deg); }
 summary em { font-style:normal; font-size:13px; color:var(--dim); font-weight:400; }
 .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(540px,1fr));
         gap:20px; padding:6px 0 26px; }
 figure { margin:0; background:var(--panel); border-radius:14px; overflow:hidden;
          scroll-margin-top:70px; }
 figure.flash { outline:2px solid var(--accent); }
 .stage { position:relative; aspect-ratio:16/9; overflow:hidden;
          background:#000 50%/cover no-repeat; }
 .stage.fb::after { content:""; position:absolute; inset:0; background:rgba(0,0,0,.3); }
 .stage img { position:absolute; }
 .box { position:absolute; left:5%; right:5%; bottom:5%; background:rgba(255,255,255,.94);
        color:#222233; border-radius:16px; padding:9px 15px 11px; }
 .plate { display:inline-block; background:#5d5882; color:#fff; border-radius:11px;
          padding:1px 10px; font-size:11.5px; }
 .tag { display:inline-block; border-radius:11px; padding:1px 8px; font-size:10.5px;
        margin-left:6px; color:#fff; }
 .tag.o { background:#b04444; } .tag.n { background:#2e8060; }
 .txt { margin:4px 0 0; font-size:13px; }
 .old b { background:rgba(196,60,60,.18); color:#a52f2f; border-radius:4px; padding:0 3px; }
 .new b { background:rgba(28,132,92,.18); color:#126b48; border-radius:4px; padding:0 3px; }
 figcaption { padding:9px 14px 13px; font-size:12.5px; color:var(--dim); }
 .jpline { color:#cfc9ee; font-size:13.5px; margin-top:3px; }
 .jpline i { color:#7d77a5; font-size:11px; margin-right:6px; font-style:normal; }
 .empty { padding:40px 24px; color:var(--dim); }
 @media (max-width:700px){ .grid{grid-template-columns:1fr} details{margin:0 12px}
   .topbar{padding-left:64px} .home{padding-top:64px} }
</style>
<button id="burger" aria-label="Menu" hidden>&#9776;</button>
<div id="scrim"></div>
<nav id="drawer"></nav>
<main id="app"></main>
<script>
// Events known to have been re-uploaded on their own dates but not yet diffed, so the
// map shows the whole territory rather than implying event 1 is all there is.
const PENDING = [24, 31, 74, 75, 111, 155];
const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const strip = (h) => h.replace(/<[^>]*>/g, "");
const hl = (s, q) => !q ? esc(s)
  : esc(s).replace(new RegExp("(" + q.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&") + ")", "ig"),
                   "<mark>$1</mark>");

let D = null, view = { name: "home", ev: null, q: "" };

/* ---------- frame rendering ---------- */
function panel(f, old) {
  const layers = f.layers.map((l) => {
    const s = D.sprites[l.key];
    return s ? `<img loading="lazy" alt="" src="sprites/${l.key}.webp"`
             + ` style="left:${(s.left + l.dx).toFixed(3)}%;top:${s.top}%;`
             + `width:${s.w}%;height:${s.h}%">` : "";
  }).join("");
  const bg = f.cover ? `background:${f.cover === "white" ? "#fff" : "#000"}`
                     : `background-image:url('${D.bgBase}/${f.bg}/${f.bg}.webp')`;
  const name = old && f.speakerOld ? f.speakerOld : f.speaker;
  const ver = old ? "BEFORE " + D.comparison.old_asset_version
                  : "AFTER " + D.comparison.new_asset_version;
  return `<div class="stage${f.flashback ? " fb" : ""}" style="${bg}">${layers}`
       + `<div class="box"><span class="plate">${esc(name)}</span>`
       + `<span class="tag ${old ? "o" : "n"}">${ver}</span>`
       + `<p class="txt ${old ? "old" : "new"}">${old ? f.old : f.new}</p></div></div>`;
}
const figure = (ev, ep, f) => `<figure id="f-${ev.id}-${ep.no}-${f.talkIndex}">`
  + panel(f, true) + panel(f, false)
  + `<figcaption>#${f.talkIndex}`
  + (f.jp ? `<div class="jpline"><i>JP</i>${esc(f.jp)}</div>` : "")
  + `</figcaption></figure>`;

/* ---------- home ---------- */
function searchLines(q) {
  const out = [];
  if (q.length < 2) return out;
  const needle = q.toLowerCase();
  for (const ev of D.events) for (const ep of ev.episodes) for (const f of ep.frames) {
    const hay = (strip(f.old) + " " + strip(f.new) + " " + f.speaker + " " + f.jp).toLowerCase();
    if (hay.includes(needle)) out.push({ ep, ev, f });
    if (out.length > 300) return out;
  }
  return out;
}
function results() {
  const q = view.q, ql = q.toLowerCase();
  const evs = D.events.filter((e) => !q
    || `event ${e.id} ${e.name} ${e.nameJp} ${e.unit}`.toLowerCase().includes(ql)
    || e.episodes.some((ep) => ep.title.toLowerCase().includes(ql)));
  const hits = searchLines(q);

  document.getElementById("results").innerHTML = `
    ${hits.length ? `<div class="sec">${hits.length > 300 ? "300+" : hits.length}
        matching lines</div>` + hits.slice(0, 40).map((h) => `
      <a class="hit" href="#/e${h.ev.id}/ep${String(h.ep.no).padStart(2, "0")}/${h.f.talkIndex}">
        <div class="who">Event ${h.ev.id} · Ep ${h.ep.no} · #${h.f.talkIndex} ·
          <b>${esc(h.f.speaker)}</b></div>
        <div class="o">− ${hl(strip(h.f.old), q)}</div>
        <div class="n">+ ${hl(strip(h.f.new), q)}</div>
      </a>`).join("") + (hits.length > 40
        ? `<div class="hint">…and ${hits.length - 40} more. Refine the search.</div>` : "")
      : ""}
    <div class="sec">Events${q ? ` matching “${esc(q)}”` : ""}</div>
    <div class="cards">
      ${evs.map((e) => `<a class="card" href="#/e${e.id}">
        <h3>Event ${e.id} · ${hl(e.name, q)}</h3>
        <div class="jp">${esc(e.nameJp || "")}</div>
        <div class="row"><span class="pill hot">${e.changed} changed lines</span>
          <span class="pill">${e.episodes.length} episodes</span>
          ${e.unit ? `<span class="pill">${esc(e.unit)}</span>` : ""}</div></a>`).join("")
      || `<div class="empty">No event matches “${esc(q)}”.</div>`}
      ${q ? "" : PENDING.map((id) => `<span class="card soon"><h3>Event ${id}</h3>
        <div class="jp">re-uploaded, not yet diffed</div></span>`).join("")}
    </div>`;
}

function home() {
  document.getElementById("burger").hidden = true;
  // Render the shell once and only ever replace #results afterwards. Re-rendering the
  // whole page per keystroke would destroy and recreate the input, which loses the
  // caret and — the reason it matters here — aborts IME composition, making the
  // Japanese search unusable.
  if (!document.getElementById("q")) {
    const totalLines = D.events.reduce((n, e) => n + e.changed, 0);
    document.getElementById("app").innerHTML = `<div class="home">
      <div class="hero">
        <h1>Project Sekai EN — official retranslation</h1>
        <p>Every story line the English release quietly rewrote, shown before and after
           over the scene the game actually draws for it. Backgrounds are served by
           storage.sekai.best; the posed characters are rendered from the official
           Live2D models.</p>
        <div class="vers">EN asset <b>${D.comparison.old_asset_version}</b> →
          <b>${D.comparison.new_asset_version}</b> · ${totalLines} changed lines</div>
      </div>
      <input id="q" placeholder="Search events, episodes, characters or dialogue…"
             autocomplete="off">
      <div class="hint">Press <b>/</b> to search. Try “Shiho”, “bass”, “rain”, or 星.</div>
      <div id="results"></div></div>`;
    const box = document.getElementById("q");
    box.value = view.q;
    let composing = false;
    box.addEventListener("compositionstart", () => { composing = true; });
    box.addEventListener("compositionend", () => { composing = false; view.q = box.value; results(); });
    box.addEventListener("input", () => {
      if (composing) return;             // mid-IME: the value is not a query yet
      view.q = box.value;
      results();
    });
  }
  results();
}

/* ---------- event ---------- */
function event(ev, openEp) {
  document.getElementById("burger").hidden = false;
  document.getElementById("app").innerHTML = `
    <div class="topbar"><a href="#/" title="All events">←</a>
      <h2>Event ${ev.id} · ${esc(ev.name)}</h2>
      <span class="meta">${ev.changed} changed lines · ${ev.episodes.length} episodes ·
        ${D.comparison.old_asset_version} → ${D.comparison.new_asset_version}</span>
      <input id="filter" placeholder="Filter lines in this event…" autocomplete="off">
    </div>
    ${ev.episodes.map((ep) => `<details id="ep${String(ep.no).padStart(2, "0")}"
        ${!openEp || openEp === "ep" + String(ep.no).padStart(2, "0") ? "open" : ""}>
      <summary>Episode ${ep.no} — ${esc(ep.title)}
        <em>${ep.frames.length} changed lines</em></summary>
      <div class="grid">${ep.frames.map((f) => figure(ev, ep, f)).join("")}</div>
    </details>`).join("")}`;

  drawer(ev);
  const filt = document.getElementById("filter");
  filt.oninput = () => {
    const q = filt.value.toLowerCase();
    for (const ep of ev.episodes) {
      const el = document.getElementById("ep" + String(ep.no).padStart(2, "0"));
      let shown = 0;
      ep.frames.forEach((f) => {
        const fig = document.getElementById(`f-${ev.id}-${ep.no}-${f.talkIndex}`);
        const hay = (strip(f.old) + strip(f.new) + f.speaker + f.jp).toLowerCase();
        const on = !q || hay.includes(q);
        fig.style.display = on ? "" : "none";
        if (on) shown++;
      });
      el.style.display = shown ? "" : "none";
      el.querySelector("em").textContent = q ? `${shown} of ${ep.frames.length} lines`
                                             : `${ep.frames.length} changed lines`;
      if (q) el.open = true;
    }
  };
}

function drawer(ev) {
  document.getElementById("drawer").innerHTML =
    `<div class="nav-h">Browse</div><a class="nav-ev" href="#/">← All events</a>`
    + `<div class="nav-h">Events</div>`
    + D.events.map((e) => `<a class="nav-ev${e.id === ev.id ? " on" : ""}" href="#/e${e.id}">`
        + `Event ${e.id} · ${esc(e.name)}<small>${e.changed} changed lines</small></a>`).join("")
    + PENDING.map((id) => `<span class="nav-ev soon">Event ${id}<small>not yet diffed</small></span>`).join("")
    + `<div class="nav-h">Episodes — event ${ev.id}</div>`
    + ev.episodes.map((ep) => `<a class="nav-ep" data-ep="ep${String(ep.no).padStart(2, "0")}"
        href="#/e${ev.id}/ep${String(ep.no).padStart(2, "0")}">`
        + `<i>${ep.no}.</i> ${esc(ep.title)} <i>${ep.frames.length}</i></a>`).join("")
    + `<div class="nav-h">All episodes</div>`
    + `<a class="nav-ep" id="expand" href="#">Expand all</a>`
    + `<a class="nav-ep" id="collapse" href="#">Collapse all</a>`;
}

/* ---------- routing ---------- */
function route() {
  const m = (location.hash || "#/").slice(2).split("/");   // e1 / ep03 / 19
  if (!m[0]) { view = { name: "home", ev: null, q: view.q }; return home(); }
  const ev = D.events.find((e) => "e" + e.id === m[0]);
  if (!ev) { view.name = "home"; return home(); }
  event(ev, m[1]);
  if (m[1]) {
    const el = document.getElementById(m[1]);
    if (el) { el.open = true;
      const target = m[2] ? document.getElementById(`f-${ev.id}-${parseInt(m[1].slice(2))}-${m[2]}`) : el;
      setTimeout(() => {
        // optional-call: never let a missing scrollIntoView abort the rest of the route
        (target || el).scrollIntoView?.({ behavior: "smooth", block: m[2] ? "center" : "start" });
        if (target) { target.classList.add("flash");
          setTimeout(() => target.classList.remove("flash"), 2200); }
      }, 30);
    }
  }
}

const dr = document.getElementById("drawer"), scrim = document.getElementById("scrim");
const toggle = (on) => { dr.classList.toggle("open", on); scrim.classList.toggle("open", on); };
document.getElementById("burger").onclick = () => toggle(!dr.classList.contains("open"));
scrim.onclick = () => toggle(false);
addEventListener("keydown", (e) => {
  if (e.key === "Escape") toggle(false);
  if (e.key === "/" && document.activeElement.tagName !== "INPUT") {
    const b = document.getElementById("q") || document.getElementById("filter");
    if (b) { e.preventDefault(); b.focus(); }
  }
});
dr.addEventListener("click", (e) => {
  if (e.target.closest("[data-ep]")) { toggle(false); return; }
  if (e.target.id === "expand" || e.target.id === "collapse") {
    e.preventDefault();
    const open = e.target.id === "expand";
    document.querySelectorAll("main details").forEach((x) => { x.open = open; });
    return;
  }
  if (e.target.closest("a")) toggle(false);
});
addEventListener("hashchange", route);
fetch("data.json").then((r) => r.json()).then((d) => { D = d; route(); });
</script>
</html>
"""


if __name__ == "__main__":
    main()
