import "./style.css";
import payload from "./data.json";

// Sprite URLs are built at runtime, so Vite cannot rewrite them the way it does the
// ones in index.html and the CSS. Resolve them against the configured base instead of
// the document: a project page served without its trailing slash would otherwise send
// every sprite request to the domain root.
const BASE = import.meta.env.BASE_URL;

// Events known to have been re-uploaded on their own dates but not yet diffed, so the
// map shows the whole territory rather than implying event 1 is all there is.
const PENDING = [24, 31, 74, 75, 111, 155];
const esc = (s) => String(s).replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const strip = (h) => h.replace(/<[^>]*>/g, "");
const hl = (s, q) => !q ? esc(s)
  : esc(s).replace(new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"),
                   "<mark>$1</mark>");

let D = null, view = { name: "home", ev: null, q: "" };

/* ---------- frame rendering ---------- */
function panel(f, old) {
  const layers = f.layers.map((l) => {
    const s = D.sprites[l.key];
    return s ? `<img loading="lazy" decoding="async" alt="" src="${BASE}sprites/${l.key}.webp"`
             + ` style="left:${(s.left + l.dx).toFixed(3)}%;top:${s.top}%;`
             + `width:${s.w}%;height:${s.h}%">` : "";
  }).join("");
  const bg = f.cover ? `background:${f.cover === "white" ? "#fff" : "#000"}`
                     : `background-image:url('${BASE}bg/${f.bg}.webp')`;
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
    ${ev.episodes.map((ep, i) => `<details id="ep${String(ep.no).padStart(2, "0")}"
        ${openEp ? (openEp === "ep" + String(ep.no).padStart(2, "0") ? "open" : "")
                 : (i === 0 ? "open" : "")}>
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
// Bundled at build time rather than fetched, so the built site also works when opened
// straight off the filesystem: browsers treat a file:// page as a null origin and
// refuse to fetch a sibling file.
D = payload;
route();
