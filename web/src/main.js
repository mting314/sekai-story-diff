import "./style.css";
import payload from "./data.json";

// Sprite URLs are built at runtime, so Vite cannot rewrite them the way it does the
// ones in index.html and the CSS. Resolve them against the configured base instead of
// the document: a project page served without its trailing slash would otherwise send
// every sprite request to the domain root.
const BASE = import.meta.env.BASE_URL;
// Generated media can be served from elsewhere (a bucket) without moving the app.
// Falls back to the site's own base so `bun run dev` and a local dist still work.
const ASSETS = import.meta.env.VITE_ASSET_BASE || BASE;

const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const strip = (h) => h.replace(/<[^>]*>/g, "");
const hl = (s, q) => !q ? esc(s)
  : esc(s).replace(new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"),
                   "<mark>$1</mark>");

let D = null, view = { ev: null, from: "", name: "home", q: "", to: "" };
// index of every live release, oldest first — comparisons are by position, never by
// string: "5.10.x" sorts under "5.2.x" lexicographically
let ORDER = new Map();
const pos = (v) => (ORDER.has(v) ? ORDER.get(v) : -1);
const spanAll = () => [D.versions[0].version, D.versions[D.versions.length - 1].version];

/** Transitions of `e` whose change landed inside the selected window (from, to]. */
function inRange(e) {
  const lo = pos(view.from), hi = pos(view.to);
  return e.transitions.filter((t) => pos(t.newVersion) > lo && pos(t.newVersion) <= hi);
}
const rangePrefix = () => {
  const [a, b] = spanAll();
  return view.from === a && view.to === b ? "" : `r/${view.from}..${view.to}/`;
};

/* ---------- frame rendering ---------- */
function panel(f, old, tr) {
  const layers = f.layers.map((l) => {
    const s = D.sprites[l.key];
    // the filename is a hash of the sprite's own bytes, so it can be cached forever
    return s ? `<img loading="lazy" decoding="async" alt="" src="${ASSETS}sprites/${s.file}"`
             + ` style="left:${(s.left + l.dx).toFixed(3)}%;top:${s.top}%;`
             + `width:${s.w}%;height:${s.h}%">` : "";
  }).join("");
  const bg = f.cover ? `background:${f.cover === "white" ? "#fff" : "#000"}`
                     : `background-image:url('${ASSETS}bg/${f.bg}.webp')`;
  const name = old && f.speakerOld ? f.speakerOld : f.speaker;
  // the bracket belongs to the transition: one event can be rewritten at several
  // releases, and each frame must say which one it belongs to
  const ver = old ? "BEFORE " + tr.oldVersion : "AFTER " + tr.newVersion;
  // the box is a sibling of the stage, not a child: the stage is a fixed 16:9 box with
  // overflow hidden, so a narrow layout that stacks the text below the art cannot do it
  // from inside. On wide screens .box is absolutely positioned back over the stage.
  return `<div class="panel"><div class="stage${f.flashback ? " fb" : ""}" style="${bg}">`
       + `${layers}</div>`
       + `<div class="box"><span class="plate">${esc(name)}</span>`
       + `<span class="tag ${old ? "o" : "n"}">${ver}</span>`
       + `<p class="txt ${old ? "old" : "new"}">${old ? f.old : f.new}</p></div></div>`;
}
const figure = (ev, tr, ep, f) =>
  `<figure id="f-${ev.id}-${tr.newVersion}-${ep.no}-${f.talkIndex}">`
  + panel(f, true, tr) + panel(f, false, tr)
  + `<figcaption>#${f.talkIndex}`
  + (f.jp ? `<div class="jpline"><i>JP</i>${esc(f.jp)}</div>` : "")
  + `</figcaption></figure>`;

/* ---------- home ---------- */
function searchLines(q) {
  const out = [];
  if (q.length < 2) return out;
  const needle = q.toLowerCase();
  for (const ev of D.events) for (const tr of inRange(ev)) for (const ep of tr.episodes)
    for (const f of ep.frames) {
      const hay = (strip(f.old) + " " + strip(f.new) + " " + f.speaker + " " + f.jp).toLowerCase();
      if (hay.includes(needle)) out.push({ ep, ev, f, tr });
      if (out.length > 300) return out;
    }
  return out;
}
const unitName = (u) => (u || "").replace(/_/g, " ");

// How much the text actually moved. Ranked, because an event can hold several
// transitions and the card shows whichever is strongest in range — averaging would let
// two typo passes cancel out a real rewrite.
const LABELS = {
  retranslation: { rank: 3, text: "substantial rewrite" },
  revised:       { rank: 2, text: "revised wording" },
  punctuation:   { rank: 1, text: "punctuation only" },
};
const strongest = (transitions) =>
  transitions.reduce((best, t) =>
    !best || (LABELS[t.label]?.rank ?? 0) > (LABELS[best]?.rank ?? 0) ? t.label : best,
  null);
const badge = (label) =>
  label ? `<span class="pill mag ${label}">${LABELS[label]?.text ?? label}</span>` : "";

function card(e, q, href) {
  const trs = href ? inRange(e) : [];
  const lines = trs.reduce((n, t) => n + t.changed, 0);
  const eps = new Set(trs.flatMap((t) => t.episodes.map((ep) => ep.no))).size;
  const tag = href ? "a" : "span";
  const link = href ? ` href="${href}"` : "";
  const art = e.banner
    ? `<div class="art" style="background-image:url('${ASSETS}${e.banner}')"></div>` : "";
  const logo = e.unitLogo ? `<img class="ulogo" alt="" src="${ASSETS}${e.unitLogo}">` : "";
  const stats = href
    ? badge(strongest(trs)) + `<span class="pill hot">${lines} changed lines</span>
       <span class="pill">${eps} episode${eps === 1 ? "" : "s"}</span>`
      + (trs.length > 1 ? `<span class="pill">${trs.length} releases</span>` : "")
    : `<span class="pill wait">not yet diffed</span>`;
  return `<${tag} class="card${href ? "" : " soon"}" style="--u:${e.colour || "#8f89b5"}"${link}>
    ${art}
    <div class="cbody">
      <h3>${q ? hl(e.name, q) : esc(e.name)}</h3>
      <div class="jp">${esc(e.nameJp || "")}</div>
      ${trs.length ? `<div class="vpair">${trs.length === 1
          ? `${trs[0].oldVersion} → ${trs[0].newVersion}`
          : `${trs[0].oldVersion} → ${trs[trs.length - 1].newVersion}`}</div>` : ""}
      <div class="row">${logo}${stats}
        ${e.unit ? `<span class="pill unit">${esc(unitName(e.unit))}</span>` : ""}</div>
    </div></${tag}>`;
}

function results() {
  const q = view.q, ql = q.toLowerCase();
  const evs = D.events
    .filter((e) => inRange(e).length)
    .filter((e) => !q
      || `${e.name} ${e.nameJp} ${e.unit}`.toLowerCase().includes(ql)
      || e.transitions.some((t) => t.episodes.some((ep) => ep.title.toLowerCase().includes(ql))));
  const hits = searchLines(q);

  const shown = evs.reduce((n, e) => n + inRange(e).reduce((m, t) => m + t.changed, 0), 0);
  const trs = evs.reduce((n, e) => n + inRange(e).length, 0);
  const tally = document.getElementById("tally");
  if (tally) {
    tally.textContent = `${evs.length} event${evs.length === 1 ? "" : "s"} · `
      + `${shown.toLocaleString()} changed lines · ${trs} release${trs === 1 ? "" : "s"}`;
  }
  document.getElementById("results").innerHTML = `
    ${hits.length ? `<div class="sec">${hits.length > 300 ? "300+" : hits.length}
        matching lines</div>` + hits.slice(0, 40).map((h) => `
      <a class="hit" href="#/${rangePrefix()}e${h.ev.id}/ep${String(h.ep.no).padStart(2, "0")}/${h.f.talkIndex}">
        <div class="who">${esc(h.ev.name)} · Ep ${h.ep.no} · #${h.f.talkIndex} ·
          <b>${esc(h.f.speaker)}</b></div>
        <div class="o">− ${hl(strip(h.f.old), q)}</div>
        <div class="n">+ ${hl(strip(h.f.new), q)}</div>
      </a>`).join("") + (hits.length > 40
        ? `<div class="hint">…and ${hits.length - 40} more. Refine the search.</div>` : "")
      : ""}
    <div class="sec">Events${q ? ` matching “${esc(q)}”` : ""}</div>
    <div class="cards">
      ${evs.map((e) => card(e, q, `#/${rangePrefix()}e${e.id}`)).join("")
      || `<div class="empty">No event matches “${esc(q)}”.</div>`}
      ${q ? "" : (D.pending || []).map((e) => card(e, "", null)).join("")}
    </div>`;
}

function home() {
  document.getElementById("burger").hidden = true;
  // Render the shell once and only ever replace #results afterwards. Re-rendering the
  // whole page per keystroke would destroy and recreate the input, which loses the
  // caret and — the reason it matters here — aborts IME composition, making the
  // Japanese search unusable.
  if (!document.getElementById("q")) {
    const opts = (sel) => D.versions.map((v) =>
      `<option value="${v.version}"${v.version === sel ? " selected" : ""}>${v.version} · ${v.date}</option>`
    ).join("");
    document.getElementById("app").innerHTML = `<div class="home">
      <div class="hero">
        <h1>Project Sekai EN — official retranslation</h1>
        <p>Every story line the English release quietly rewrote, shown before and after
           over the scene the game actually draws for it. Backgrounds are served by
           storage.sekai.best; the posed characters are rendered from the official
           Live2D models.</p>
        <div class="picker">
          <label>from <select id="from">${opts(view.from)}</select></label>
          <label>to <select id="to">${opts(view.to)}</select></label>
          <button id="allv" type="button">whole window</button>
          <span id="tally" class="tally"></span>
        </div>
      </div>
      <input id="q" placeholder="Search events, episodes, characters or dialogue…"
             autocomplete="off">
      <div class="hint">Press <b>/</b> to search. Try “Shiho”, “bass”, “rain”, or 星.</div>
      <div id="results"></div></div>`;
    const sync = (which) => {
      const el = document.getElementById(which);
      el.onchange = () => {
        view[which] = el.value;
        // a backwards range selects nothing; nudge the other end rather than show zero
        if (pos(view.from) > pos(view.to)) {
          const other = which === "from" ? "to" : "from";
          view[other] = el.value;
          document.getElementById(other).value = el.value;
        }
        location.hash = "#/" + rangePrefix();
        results();
      };
    };
    sync("from"); sync("to");
    document.getElementById("allv").onclick = () => {
      [view.from, view.to] = spanAll();
      document.getElementById("from").value = view.from;
      document.getElementById("to").value = view.to;
      location.hash = "#/";
      results();
    };

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
const epId = (tr, ep) => `t${tr.newVersion.replace(/\./g, "_")}-ep${String(ep.no).padStart(2, "0")}`;

function event(ev, openEp) {
  document.getElementById("burger").hidden = false;
  const trs = inRange(ev);
  const lines = trs.reduce((n, t) => n + t.changed, 0);
  // One event can be rewritten at several releases. Each gets its own section so a
  // line edited twice is shown twice, against the release that actually changed it.
  const multi = trs.length > 1;

  document.getElementById("app").innerHTML = `
    <div class="topbar" style="--u:${ev.colour || "#8f89b5"}"><a href="#/${rangePrefix()}" title="All events">←</a>
      ${ev.unitLogo ? `<img class="ulogo big" alt="" src="${ASSETS}${ev.unitLogo}">` : ""}
      <h2>${esc(ev.name)}</h2>
      <span class="meta">${lines} changed lines ·
        ${trs.length} release${trs.length === 1 ? "" : "s"}</span>
      ${badge(strongest(trs))}
      <input id="filter" placeholder="Filter lines in this event…" autocomplete="off">
    </div>
    ${trs.map((tr, ti) => (multi ? `<div class="relhdr" style="--u:${ev.colour}">
        <b>${tr.oldVersion} → ${tr.newVersion}</b>
        <span>${tr.newReleasedAt || ""} · ${tr.changed} changed lines ·
          ${(tr.depth * 100).toFixed(1)}% of the text</span>
        ${badge(tr.label)}</div>` : "")
      + tr.episodes.map((ep, i) => `<details id="${epId(tr, ep)}"
          ${openEp ? (openEp === epId(tr, ep) ? "open" : "")
                   : (ti === 0 && i === 0 ? "open" : "")}>
        <summary>Episode ${ep.no} — ${esc(ep.title)}
          <em>${ep.frames.length} changed lines</em></summary>
        <div class="grid">${ep.frames.map((f) => figure(ev, tr, ep, f)).join("")}</div>
      </details>`).join("")).join("")}`;

  drawer(ev, trs);
  const filt = document.getElementById("filter");
  filt.oninput = () => {
    const q = filt.value.toLowerCase();
    let total = 0;
    for (const tr of trs) for (const ep of tr.episodes) {
      const el = document.getElementById(epId(tr, ep));
      let shown = 0;
      ep.frames.forEach((f) => {
        const fig = document.getElementById(`f-${ev.id}-${tr.newVersion}-${ep.no}-${f.talkIndex}`);
        const hay = (strip(f.old) + strip(f.new) + f.speaker + f.jp).toLowerCase();
        const on = !q || hay.includes(q);
        fig.style.display = on ? "" : "none";
        if (on) shown++;
      });
      el.style.display = shown ? "" : "none";
      el.querySelector("em").textContent = q ? `${shown} of ${ep.frames.length} lines`
                                             : `${ep.frames.length} changed lines`;
      if (q) el.open = true;
      total += shown;
    }
    // hiding every episode used to leave a silently blank page with no explanation
    let none = document.getElementById("nomatch");
    if (!none) {
      none = document.createElement("div");
      none.id = "nomatch";
      none.className = "empty";
      document.getElementById("app").append(none);
    }
    none.textContent = q && !total ? `No line in this event matches “${filt.value}”.` : "";
    none.style.display = q && !total ? "" : "none";
  };
}

function drawer(ev, trs) {
  document.getElementById("drawer").innerHTML =
    `<div class="nav-h">Browse</div>`
    + `<a class="nav-ev" href="#/${rangePrefix()}">← All events</a>`
    + `<div class="nav-h">Events in range</div>`
    + D.events.filter((e) => inRange(e).length).map((e) => {
        const n = inRange(e).reduce((m, t) => m + t.changed, 0);
        return `<a class="nav-ev${e.id === ev.id ? " on" : ""}" href="#/${rangePrefix()}e${e.id}"`
             + ` style="--u:${e.colour || "#8f89b5"}">${esc(e.name)}`
             + `<small>${n} changed lines</small></a>`;
      }).join("")
    + trs.map((tr) => `<div class="nav-h">${tr.oldVersion} → ${tr.newVersion}</div>`
        + tr.episodes.map((ep) => `<a class="nav-ep" data-ep="${epId(tr, ep)}"`
            + ` href="#/${rangePrefix()}e${ev.id}/${epId(tr, ep)}">`
            + `<i>${ep.no}.</i> ${esc(ep.title)} <i>${ep.frames.length}</i></a>`).join("")).join("")
    + `<div class="nav-h">All episodes</div>`
    + `<a class="nav-ep" id="expand" href="#">Expand all</a>`
    + `<a class="nav-ep" id="collapse" href="#">Collapse all</a>`;
}

/* ---------- routing ---------- */
// #/                                   whole window
// #/r/5.4.0.20..5.5.1.20/              explicit range
// #/[r/<a>..<b>/]e1/t5_4_0_30-ep03/19  event, transition+episode, line
function route() {
  const parts = (location.hash || "#/").slice(2).split("/").filter(Boolean);
  [view.from, view.to] = spanAll();
  if (parts[0] === "r" && parts[1] && parts[1].includes("..")) {
    const [a, b] = parts.shift() && parts.shift().split("..");
    if (ORDER.has(a) && ORDER.has(b) && pos(a) <= pos(b)) { view.from = a; view.to = b; }
  }
  if (!parts.length) { view.name = "home"; return home(); }

  const ev = D.events.find((e) => "e" + e.id === parts[0]);
  if (!ev || !inRange(ev).length) { view.name = "home"; return home(); }
  view.name = "event";
  event(ev, parts[1]);
  if (parts[1]) {
    const el = document.getElementById(parts[1]);
    if (el) {
      el.open = true;
      const tr = inRange(ev).find((t) => parts[1].startsWith("t" + t.newVersion.replace(/\./g, "_")));
      const target = parts[2] && tr
        ? document.getElementById(`f-${ev.id}-${tr.newVersion}-${parseInt(parts[1].slice(-2))}-${parts[2]}`)
        : el;
      setTimeout(() => {
        // optional-call: never let a missing scrollIntoView abort the rest of the route
        (target || el).scrollIntoView?.({ behavior: "smooth", block: parts[2] ? "center" : "start" });
        if (target && target !== el) {
          target.classList.add("flash");
          setTimeout(() => target.classList.remove("flash"), 2200);
        }
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
// Bundled at build time rather than fetched, so the built site also works when opened
// straight off the filesystem: browsers treat a file:// page as a null origin and
// refuse to fetch a sibling file.
D = payload;
ORDER = new Map(D.versions.map((v, i) => [v.version, i]));
[view.from, view.to] = spanAll();
route();
