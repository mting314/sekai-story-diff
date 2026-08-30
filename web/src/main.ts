import "./style.css";
import payloadJson from "./data.json";
import type {
  EventEntry, Episode, Frame, Html, Magnitude, Payload, PendingEvent, ReaderNo,
  Transition,
} from "./payload";

// resolveJsonModule infers the payload's type from the file, which is unsound here:
// `dropped` and `pending` are empty in every build so far and infer as never[], and
// `cover` is "" on all 1,107 frames though the code branches on "white". payload.d.ts
// is the declared shape; test/check-range.mjs asserts the real file matches it.
const payload = payloadJson as unknown as Payload;

/** `document.getElementById` that fails loudly rather than returning null.
 *
 *  Every id this file asks for is one it just rendered, so a miss is a bug in the
 *  template, not a case to handle. Sprinkling `!` would say the same thing and lose the
 *  error message. */
const el = <T extends HTMLElement = HTMLElement>(id: string): T => {
  const found = document.getElementById(id);
  if (!found) throw new Error(`no #${id} in the document`);
  return found as T;
};

// Sprite URLs are built at runtime, so Vite cannot rewrite them the way it does the
// ones in index.html and the CSS. Resolve them against the configured base instead of
// the document: a project page served without its trailing slash would otherwise send
// every sprite request to the domain root.
const BASE = import.meta.env.BASE_URL;
// Generated media can be served from elsewhere (a bucket) without moving the app.
// Falls back to the site's own base so `bun run dev` and a local dist still work.
const ASSETS = import.meta.env.VITE_ASSET_BASE || BASE;

const ESCAPE: Record<string, string> =
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
/** Plain text -> markup-safe. Returns Html because the result is now escaped. */
const esc = (s: string | number): Html =>
  String(s).replace(/[&<>"]/g, (c) => ESCAPE[c]) as Html;
// The payload stores each line as HTML — Python's html.escape() has already turned
// & < > " ' into entities, and the diff runs are real <b> tags. Injecting that into
// .txt is correct, but every *other* use wants plain text, so the entities have to come
// back out. Leaving them in escaped the ampersand a second time and printed a literal
// "it&#x27;s" in the search results, and — less visibly — made the search haystack
// contain "can&#x27;t", so no query with an apostrophe could ever match.
const ENTITY: Record<string, string> =
  { "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'" };
// one left-to-right pass, so "&amp;lt;" decodes to "&lt;" and is not decoded twice
/** Html -> plain text. Only accepts Html: handing it an already-plain string is the
 *  mistake that left `&#x27;` in the search haystack. */
const strip = (h: Html): string => h.replace(/<[^>]*>/g, "")
                      .replace(/&(?:amp|lt|gt|quot|#x27);/g, (m) => ENTITY[m]);
const hl = (s: string, q: string): Html => !q ? esc(s)
  : esc(s).replace(new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"),
                   "<mark>$1</mark>") as Html;

interface View { from: string; name: string; q: string; to: string }
let D: Payload;
const view: View = { from: "", name: "home", q: "", to: "" };
// index of every live release, oldest first — comparisons are by position, never by
// string: "5.10.x" sorts under "5.2.x" lexicographically
let ORDER = new Map<string, number>();
const pos = (v: string): number => (ORDER.has(v) ? ORDER.get(v)! : -1);
const spanAll = (): [string, string] =>
  [D.versions[0].version, D.versions[D.versions.length - 1].version];

/** Transitions of `e` whose change landed inside the selected window (from, to]. */
function inRange(e: EventEntry): Transition[] {
  const lo = pos(view.from), hi = pos(view.to);
  return e.transitions.filter((t) => pos(t.newVersion) > lo && pos(t.newVersion) <= hi);
}
const rangePrefix = () => {
  const [a, b] = spanAll();
  return view.from === a && view.to === b ? "" : `r/${view.from}..${view.to}/`;
};

/* ---------- frame rendering ---------- */
function panel(f: Frame, old: boolean, tr: Transition): Html {
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
  // 23 frames change only the name plate — "Kanade's Father" to "Kanade's Dad",
  // "Tsukasa ＆Emu" to "Tsukasa, Emu". The body text is identical, so with the name left
  // unmarked the pair reads as two copies of the same frame and the edit is invisible.
  // Mark it with the same red/green the body diff uses.
  const renamed = f.speakerOld && f.speakerOld !== f.speaker;
  // the bracket belongs to the transition: one event can be rewritten at several
  // releases, and each frame must say which one it belongs to
  // An inserted line has no "after" because it has no "before" — it is simply the line
  // this release added, so say that rather than implying a rewrite.
  const ver = old ? "BEFORE " + tr.oldVersion
                  : (f.inserted ? "INSERTED AT " : "AFTER ") + tr.newVersion;
  // The dialogue lives *inside* the stage now. It used to be a sibling so a narrow
  // layout could stack it below the art, but that stopped being true when the mobile
  // rules went back to overlaying — and being inside is what lets it size in cqmin
  // against the stage's own box, the way the game scales every dialogue dimension.
  return `<div class="panel"><div class="stage${f.flashback ? " fb" : ""}" style="${bg}">`
       + `${layers}`
       + `<div class="dlg"><div class="spk-row">`
       + `<span class="spk${renamed ? (old ? " old" : " new") : ""}">`
       + `${renamed ? `<b>${esc(name)}</b>` : esc(name)}</span>`
       + `<span class="spk-rule" aria-hidden="true"></span></div>`
       + `<span class="tag ${old ? "o" : f.inserted ? "i" : "n"}">${ver}</span>`
       + `<p class="txt ${old ? "old" : "new"}">${old ? f.old : f.new}</p></div>`
       + `</div></div>` as Html;
}
// Read this exact line in context, in a full story reader.
//
// Cleista's reader rather than sekai.best: sekai.best's /storyreader/ route reaches an
// episode but has no line anchor, so it could only ever drop you at the top of a
// twenty-minute scene. This one takes ?line=N.
//
// ?line is NOT our line number. It counts the reader's *steps*, and a full-screen telop
// is a step you click through, so it runs ahead of TalkData by however many telops came
// before. 94% of our frames drift, by up to seven lines. readerLine is computed in the
// builder from the same rule their steps.js uses; f.talkIndex must not be substituted.
//
// Neither reader puts the language in the URL; both read it from a stored preference,
// so a reader set to JP will land on the Japanese text of the right line.
const READER = "https://pjsk.cleista.cc/#/read";
// The line is a parameter rather than read off the frame inside the template: a brand
// does not survive template interpolation, so `?line=${f.readerLine}` and
// `?line=${f.talkIndex}` are both just `string` there and the compiler cannot tell them
// apart. Taking a ReaderNo argument is what makes substituting talkIndex an error.
const readerHref = (ev: EventEntry, ep: Episode, line: ReaderNo): string =>
  `${READER}/${ev.kind === "arc" ? "unit" : "event"}`
  + `/${ev.bundleName}/${ep.scenarioId}?line=${line}`;

/* ---------- lines edited more than once ---------- */
// A line can move at one release and move again at a later one. The page shows both, one
// section per release, but nothing connects them, so you have to notice by hand.
//
// Worth connecting because in this corpus the answer is always the same: all five such
// lines are *reverts* that end exactly where they started. Someone capitalised "dad" and
// undid it fifteen releases later; someone renamed Kanade's father and undid it two
// releases later. That is an editorial signal, and it is invisible one frame at a time.
//
// Deliberately not a "net diff across releases" view, which is the obvious shape and the
// wrong one: composing these five pairs produces five empty diffs. The finding is that
// the composition is empty, so it belongs on the frame as a note.
interface Occurrence { tr: Transition; ep: Episode; f: Frame }

/** Every (episode, line) in `ev` that more than one release touched, oldest first.
 *
 *  Built over *all* the event's transitions rather than the in-range ones: a line edited
 *  outside the current window is still worth knowing about, and the note links with an
 *  explicit range so it resolves regardless. */
function editedTwice(ev: EventEntry): Map<string, Occurrence[]> {
  const by = new Map<string, Occurrence[]>();
  for (const tr of ev.transitions) {
    for (const ep of tr.episodes) {
      for (const f of ep.frames) {
        const key = `${ep.no}|${f.talkIndex}`;
        if (!by.has(key)) by.set(key, []);
        by.get(key)!.push({ tr, ep, f });
      }
    }
  }
  for (const [key, hits] of by) {
    if (hits.length < 2) by.delete(key);
    else hits.sort((a, b) => pos(a.tr.newVersion) - pos(b.tr.newVersion));
  }
  return by;
}

/** Did the whole chain end where it started — text and speaker both? */
const isRevert = (hits: Occurrence[]): boolean => {
  const first = hits[0].f, last = hits[hits.length - 1].f;
  // A chain that opens with an insertion has no state to return to, and `old` is "" on
  // those, so the comparison below would call any later deletion-to-empty a revert.
  if (first.inserted) return false;
  return strip(first.old) === strip(last.new) && first.speakerOld === last.speaker;
};

const againNote = (ev: EventEntry, hits: Occurrence[], self: Frame): Html => {
  const others = hits.filter((h) => h.f !== self);
  if (!others.length) return "" as Html;
  const links = others.map((h) =>
    `<a href="#/r/${h.tr.oldVersion}..${h.tr.newVersion}/${ev.slug}/${h.ep.slug}`
    + `/${h.f.talkIndex}?v=${h.tr.newVersion}">${h.tr.newVersion}</a>`).join(", ");
  return `<span class="again" title="This line was changed at more than one release">`
       + `↻ also edited at ${links}`
       + (isRevert(hits) ? ` — <b>ends unchanged</b>` : "")
       + `</span>` as Html;
};

const figure = (ev: EventEntry, tr: Transition, ep: Episode, f: Frame,
                again: Map<string, Occurrence[]>): Html =>
  `<figure id="f-${ev.id}-${tr.newVersion}-${ep.no}-${f.talkIndex}">`
  + (f.inserted ? "" : panel(f, true, tr)) + panel(f, false, tr)
  + `<figcaption><span class="ln">#${f.talkIndex}</span>`
  + (ev.bundleName && ep.scenarioId && f.readerLine
      ? `<a class="ctx" target="_blank" rel="noopener noreferrer"
           title="Read this line in context on Cleista's SEKAI Reader"
           href="${readerHref(ev, ep, f.readerLine)}">in context ↗</a>` : "")
  + againNote(ev, again.get(`${ep.no}|${f.talkIndex}`) ?? [], f)
  + (f.jp ? `<div class="jpline"><i>JP</i>${esc(f.jp)}</div>` : "")
  + `</figcaption></figure>` as Html;

// Banner art with the arc fallback, shared by the drawer and the release list — three
// copies of this was where drift would start.
//
// The full-size banner, not a thumbnail variant: home is the default entry point, so the
// cards have already fetched these and reuse costs nothing, whereas a separate small set
// would share no cache and make the common path download both. Always an <img
// loading="lazy">, never card()'s CSS background-image, because backgrounds fetch as soon
// as the element renders — that would pull every banner on a page whether or not the
// drawer is open or the row is scrolled to.
const thumb = (e: EventEntry, cls: string): Html => (e.banner
  ? `<img class="${cls}" loading="lazy" decoding="async" alt="" src="${ASSETS}${e.banner}">`
  : `<span class="${cls} blank">${e.unitLogo
      ? `<img loading="lazy" alt="" src="${ASSETS}${e.unitLogo}">` : ""}</span>`) as Html;

/* ---------- releases ---------- */
// The site answers "what changed in this event". This answers "what did this release
// change" — which the range view already renders, so this is only the index over it.
//
// Derived here rather than in the payload: a row needs counts, and those are already
// aggregated on each transition, so the pivot is 46 transitions rather than the 1,107
// frames underneath them. Nothing here needs the pipeline to emit anything new.
/** One adjacent version pair and the events whose text moved at it. */
interface Release {
  changed: number;
  date: string;
  from: string;
  hits: { ev: EventEntry; tr: Transition }[];
  to: string;
}

function releases(): Release[] {
  const byPair = new Map<string, { ev: EventEntry; tr: Transition }[]>();
  for (const ev of D.events) {
    for (const tr of ev.transitions) {
      const key = `${tr.oldVersion}..${tr.newVersion}`;
      if (!byPair.has(key)) byPair.set(key, []);
      byPair.get(key)!.push({ ev, tr });
    }
  }
  // Walk every adjacent pair in the live window, not just the ones that changed: a
  // release that moved nothing is a result the sweep produced, not missing data.
  const out: Release[] = [];
  for (let i = 1; i < D.versions.length; i++) {
    const from = D.versions[i - 1], to = D.versions[i];
    const hits = byPair.get(`${from.version}..${to.version}`) || [];
    out.push({
      changed: hits.reduce((n, h) => n + h.tr.changed, 0),
      date: to.date,
      from: from.version,
      // no release-level magnitude: it is the strongest of its events, which on a
      // release touching eight of them says nothing about any particular one. Each
      // event tile carries its own.
      hits: hits.sort((a, b) => b.tr.changed - a.tr.changed),
      to: to.version,
    });
  }
  return out.reverse();
}

function releasesPage() {
  // no current event, so nothing for the drawer to scope to — same as home
  el("burger").hidden = true;
  const rows = releases();
  const live = rows.filter((r) => r.hits.length);
  const lines = live.reduce((n, r) => n + r.changed, 0);
  el("app").innerHTML = `<div class="home">
    <div class="hero">
      <h1>Releases</h1>
      <p>Every English asset release in the window the game's CDN still serves, and what
         each one did to the story text. ${live.length} of ${rows.length} changed
         something; the rest are listed too, because "nothing moved here" is a result of
         the sweep rather than a gap in it.</p>
      <div class="picker"><a class="relback" href="#/${rangePrefix()}">← All events</a>
        <span class="tally">${rows.length} releases ·
          ${lines.toLocaleString()} changed lines</span></div>
    </div>
    <div class="rels">${rows.map(relRow).join("")}</div>
    ${attribution()}</div>`;
}

const relRow = (r: Release): Html => {
  if (!r.hits.length) {
    return `<div class="rel quiet"><span class="rel-d">${r.date}</span>`
         + `<span class="rel-v">${r.from} → ${r.to}</span>`
         + `<span class="rel-n">no text changed</span></div>` as Html;
  }
  // per-event magnitude, not the release's strongest: a release can touch eight events
  // and rewrite only one of them, and the row above already carries the summary
  const chips = r.hits.map(({ ev, tr }) =>
    `<a class="rel-ev" style="--u:${ev.colour || "#8f89b5"}"
        href="#/r/${r.from}..${r.to}/${ev.slug}">${thumb(ev, "rel-art")}
        <span class="rel-ev-t"><b>${esc(ev.shortName || ev.name)}</b>
          <small>${tr.changed} line${tr.changed === 1 ? "" : "s"}
            ${badge(tr.label)}</small></span></a>`).join("");
  return `<a class="rel" href="#/r/${r.from}..${r.to}/">
      <span class="rel-d">${r.date}</span>
      <span class="rel-v">${r.from} → ${r.to}</span>
      <span class="rel-n">${r.hits.length} event${r.hits.length === 1 ? "" : "s"} ·
        ${r.changed.toLocaleString()} line${r.changed === 1 ? "" : "s"}</span>
    </a><div class="rel-evs">${chips}</div>` as Html;
};

/* ---------- attribution ---------- */
// This site reproduces thousands of lines of someone else's script over their character
// art. It should say whose, and say so where people actually land, rather than in a
// buried About page — hence the home footer plus a short line in the drawer, which is
// the only chrome an event page has.
const CREDITS = [
  ["https://github.com/Sekai-World/sekai-master-db-en-diff",
   "Sekai-World/sekai-master-db-en-diff",
   "the asset version index — every release's version and hash, recovered from its git history"],
  ["https://sekai.best", "sekai.best",
   "the asset mirror the backgrounds, banners and Japanese script are taken from"],
  ["https://github.com/Sekai-World/sekai-viewer", "Sekai-World/sekai-viewer",
   "the scene layout and Live2D transforms this reimplements"],
  ["https://github.com/mos9527/sssekai", "sssekai",
   "reads and decrypts the game's asset bundles"],
  ["https://pjsk.cleista.cc", "Cleista's SEKAI Reader",
   "where the “in context” links go, and the model for the dialogue styling"],
];

const attribution = () => `<footer class="attrib">
  <p><b>An unofficial fan project.</b> Not affiliated with, endorsed by, or connected to
     SEGA, Colorful Palette or Crypton Future Media.</p>
  <p>All story text, character models, backgrounds and event art belong to their owners
     — © SEGA · © Colorful Palette Inc. · © Crypton Future Media, INC.
     <a href="https://piapro.net" target="_blank" rel="noopener noreferrer">piapro.net</a>
     — and appear here only to document what changed between two official English
     releases. Nothing here is a translation of ours: both sides of every diff are the
     publisher's own text.</p>
  <p class="attrib-h">Built on other people's work</p>
  <ul>${CREDITS.map(([href, name, what]) =>
    `<li><a href="${href}" target="_blank" rel="noopener noreferrer">${name}</a> — ${what}</li>`
  ).join("")}</ul>
</footer>`;

/* ---------- home ---------- */
interface Hit { ep: Episode; ev: EventEntry; f: Frame; tr: Transition }
function searchLines(q: string): Hit[] {
  const out: Hit[] = [];
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
// The payload keys are slugs. Spelling them out matters now that they head the drawer
// groups: the casing in "MORE MORE JUMP!" and "Vivid BAD SQUAD" is the official EN
// styling, not shouting, and de-slugging alone would print "leo need".
const UNIT_NAMES: Record<string, string> = {
  leo_need: "Leo/need",
  more_more_jump: "MORE MORE JUMP!",
  vivid_bad_squad: "Vivid BAD SQUAD",
  wonderlands_showtime: "Wonderlands×Showtime",
  nightcord: "Nightcord at 25:00",
  mixed: "Mixed units",
};
const unitName = (u: string): string => UNIT_NAMES[u] || (u || "").replace(/_/g, " ");

// How much the text actually moved. Ranked, because an event can hold several
// transitions and the card shows whichever is strongest in range — averaging would let
// two typo passes cancel out a real rewrite.
const LABELS: Record<Magnitude, { rank: number; text: string }> = {
  retranslation: { rank: 3, text: "substantial rewrite" },
  revised:       { rank: 2, text: "revised wording" },
  punctuation:   { rank: 1, text: "punctuation only" },
};
const strongest = (transitions: Transition[]): Magnitude | null =>
  transitions.reduce<Magnitude | null>((best, t) =>
    !best || (LABELS[t.label]?.rank ?? 0) > (LABELS[best]?.rank ?? 0) ? t.label : best,
  null);
const badge = (label: Magnitude | null): Html =>
  (label ? `<span class="pill mag ${label}">${LABELS[label]?.text ?? label}</span>` : "") as Html;

function card(e: EventEntry | PendingEvent, q: string, href: string | null): Html {
  // a pending event has no transitions and no kind — it is only ever rendered as a
  // dead card, and href is null in exactly that case
  const trs = href && "transitions" in e ? inRange(e) : [];
  const lines = trs.reduce((n, t) => n + t.changed, 0);
  const eps = new Set(trs.flatMap((t) => t.episodes.map((ep) => ep.no))).size;
  const tag = href ? "a" : "span";
  const link = href ? ` href="${href}"` : "";
  // Unit arcs have no banner — no chapter art exists on the mirror — so they get a
  // unit-coloured panel carrying the unit logo instead of an empty slot.
  const art = e.banner
    ? `<div class="art" style="background-image:url('${ASSETS}${e.banner}')"></div>`
    : "kind" in e && e.kind === "arc"
      ? `<div class="art arcart">${e.unitLogo
          ? `<img alt="" src="${ASSETS}${e.unitLogo}">` : ""}</div>`
      : "";
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
    </div></${tag}>` as Html;
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
  el("results").innerHTML = `
    ${hits.length ? `<div class="sec">${hits.length > 300 ? "300+" : hits.length}
        matching lines</div>` + hits.slice(0, 40).map((h) => `
      <a class="hit" href="${epHref(h.ev, h.tr, h.ep, h.f.talkIndex)}">
        <div class="who">${esc(h.ev.name)} · Ep ${h.ep.no} · #${h.f.talkIndex} ·
          <b>${esc(h.f.speaker)}</b></div>
        ${h.f.inserted ? "" : `<div class="o">− ${hl(strip(h.f.old), q)}</div>`}
        <div class="n">+ ${hl(strip(h.f.new), q)}</div>
      </a>`).join("") + (hits.length > 40
        ? `<div class="hint">…and ${hits.length - 40} more. Refine the search.</div>` : "")
      : ""}
    <div class="sec">Events${q ? ` matching “${esc(q)}”` : ""}</div>
    <div class="cards">
      ${evs.map((e) => card(e, q, evHref(e))).join("")
      || `<div class="empty">No event matches “${esc(q)}”.</div>`}
      ${q ? "" : (D.pending || []).map((e) => card(e, "", null)).join("")}
    </div>`;
}

function home() {
  el("burger").hidden = true;
  // Render the shell once and only ever replace #results afterwards. Re-rendering the
  // whole page per keystroke would destroy and recreate the input, which loses the
  // caret and — the reason it matters here — aborts IME composition, making the
  // Japanese search unusable.
  if (!document.getElementById("q")) {
    const opts = (sel: string) => D.versions.map((v) =>
      `<option value="${v.version}"${v.version === sel ? " selected" : ""}>${v.version} · ${v.date}</option>`
    ).join("");
    el("app").innerHTML = `<div class="home">
      <div class="hero">
        <h1>Project Sekai EN — official retranslation</h1>
        <p>Every story line the English release quietly rewrote, shown before and after
           over the scene the game actually draws for it. Both sides come from the
           game's own asset CDN at a pinned version; the posed characters are rendered
           from the official Live2D models.</p>
        <div class="picker">
          <label>from <select id="from">${opts(view.from)}</select></label>
          <label>to <select id="to">${opts(view.to)}</select></label>
          <button id="allv" type="button">whole window</button>
          <a class="relback" href="#/releases">Browse by release →</a>
          <span id="tally" class="tally"></span>
        </div>
      </div>
      <input id="q" placeholder="Search events, episodes, characters or dialogue…"
             autocomplete="off">
      <div class="hint">Press <b>/</b> to search. Try “Shiho”, “bass”, “rain”, or 星.</div>
      <div id="results"></div>
      ${attribution()}</div>`;
    const sync = (which: "from" | "to") => {
      const sel = el<HTMLSelectElement>(which);
      sel.onchange = () => {
        view[which] = sel.value;
        // a backwards range selects nothing; nudge the other end rather than show zero
        if (pos(view.from) > pos(view.to)) {
          const other = which === "from" ? "to" : "from";
          view[other] = sel.value;
          el<HTMLSelectElement>(other).value = sel.value;
        }
        location.hash = "#/" + rangePrefix();
        results();
      };
    };
    sync("from"); sync("to");
    el("allv").onclick = () => {
      [view.from, view.to] = spanAll();
      el<HTMLSelectElement>("from").value = view.from;
      el<HTMLSelectElement>("to").value = view.to;
      location.hash = "#/";
      results();
    };

    const box = el<HTMLInputElement>("q");
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
const epId = (tr: Transition, ep: Episode): string => `t${tr.newVersion.replace(/\./g, "_")}-ep${String(ep.no).padStart(2, "0")}`;

// Every link goes through these two, so the URL shape is defined in exactly one place.
// The version is only appended when the event has more than one release in range —
// carrying it always would put a version string in 34 of 40 URLs that cannot be
// ambiguous.
const evHref = (ev: EventEntry): string => `#/${rangePrefix()}${ev.slug}`;
const epHref = (ev: EventEntry, tr: Transition, ep: Episode, line?: number): string => {
  const multi = inRange(ev).length > 1;
  return `${evHref(ev)}/${ep.slug}${line != null ? "/" + line : ""}`
       + (multi ? `?v=${tr.newVersion}` : "");
};

function event(ev: EventEntry, openEp: string): void {
  el("burger").hidden = false;
  const trs = inRange(ev);
  const lines = trs.reduce((n, t) => n + t.changed, 0);
  // One event can be rewritten at several releases. Each gets its own section so a
  // line edited twice is shown twice, against the release that actually changed it.
  const multi = trs.length > 1;
  // computed once per event, not per frame: 359 frames would otherwise each
  // rebuild the same index
  const again = editedTwice(ev);

  el("app").innerHTML = `
    <div class="topbar" style="--u:${ev.colour || "#8f89b5"}"><a href="#/${rangePrefix()}" title="All events">←</a>
      ${ev.logo ? `<img class="elogo" alt="" src="${ASSETS}${ev.logo}">`
        : ev.unitLogo ? `<img class="ulogo big" alt="" src="${ASSETS}${ev.unitLogo}">` : ""}
      <h2>${esc(ev.name)}</h2>
      <span class="meta">${lines} changed lines ·
        ${trs.length} release${trs.length === 1 ? "" : "s"}</span>
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
        <div class="grid">${ep.frames.map((f) => figure(ev, tr, ep, f, again)).join("")}</div>
      </details>`).join("")).join("")}`;

  drawer(ev, trs);
  const filt = el<HTMLInputElement>("filter");
  filt.oninput = () => {
    const q = filt.value.toLowerCase();
    let total = 0;
    for (const tr of trs) for (const ep of tr.episodes) {
      const section = el<HTMLDetailsElement>(epId(tr, ep));
      let shown = 0;
      ep.frames.forEach((f) => {
        const fig = el(`f-${ev.id}-${tr.newVersion}-${ep.no}-${f.talkIndex}`);
        const hay = (strip(f.old) + strip(f.new) + f.speaker + f.jp).toLowerCase();
        const on = !q || hay.includes(q);
        fig.style.display = on ? "" : "none";
        if (on) shown++;
      });
      section.style.display = shown ? "" : "none";
      section.querySelector("em")!.textContent = q ? `${shown} of ${ep.frames.length} lines`
                                             : `${ep.frames.length} changed lines`;
      if (q) section.open = true;
      total += shown;
    }
    // hiding every episode used to leave a silently blank page with no explanation
    let none = document.getElementById("nomatch");
    if (!none) {
      none = document.createElement("div");
      none.id = "nomatch";
      none.className = "empty";
      el("app").append(none);
    }
    none.textContent = q && !total ? `No line in this event matches “${filt.value}”.` : "";
    none.style.display = q && !total ? "" : "none";
  };
}

function navRow(e: EventEntry, n: number): Html {
  // an arc already sits under its unit's header, so drop the unit name from the label
  return `<a class="nav-ev" data-ev="${e.id}" href="${evHref(e)}"`
       + ` style="--u:${e.colour || "#8f89b5"}">${thumb(e, "nav-art")}`
       + `<span class="nav-txt"><b>${esc(e.shortName || e.name)}</b>`
       + `<small>${n} changed lines</small></span></a>` as Html;
}

// Events grouped by unit, heaviest first at both levels: units by their total changed
// lines, events within a unit by their own. Grouping is over the *in-range* events, so a
// narrow window drops whole units rather than showing empty headers.
interface NavGroup {
  unit: string; total: number; logo: string; events: { e: EventEntry; n: number }[];
}

function navGroups(): NavGroup[] {
  const by = new Map<string, NavGroup>();
  for (const e of D.events) {
    const trs = inRange(e);
    if (!trs.length) continue;
    const u = e.unit || "mixed";
    if (!by.has(u)) by.set(u, { unit: u, total: 0, logo: "", events: [] });
    const g = by.get(u)!;
    const n = trs.reduce((m, t) => m + t.changed, 0);
    g.total += n;
    g.logo ||= e.unitLogo || "";
    g.events.push({ e, n });
  }
  for (const g of by.values()) g.events.sort((a, b) => b.n - a.n);
  return [...by.values()].sort((a, b) => b.total - a.total);
}

let navRange: string | null = null;

function drawer(ev: EventEntry, trs: Transition[]): void {
  const d = el("drawer");
  const key = `${view.from}..${view.to}`;
  // The event list depends only on the range, but drawer() runs on every route change
  // including each episode deep-link. Rebuilding it there would discard and recreate 38
  // <img> elements — and reset their lazy-load state — for no change in content.
  if (navRange !== key) {
    navRange = key;
    d.innerHTML =
      `<div class="nav-h">Browse</div>`
      + `<a class="nav-ev flat" href="#/${rangePrefix()}">← All events</a>`
      + `<a class="nav-ev flat" href="#/releases">Browse by release →</a>`
      + `<div id="nav-events">`
      + navGroups().map((g) => {
          const logo = g.logo
            ? `<img class="nav-ulogo" loading="lazy" alt="" src="${ASSETS}${g.logo}">` : "";
          return `<details class="nav-grp" style="--u:${g.events[0].e.colour || "#8f89b5"}">`
               + `<summary class="nav-h unit">${logo}`
               + `<span class="nav-t">${esc(unitName(g.unit))}</span>`
               + `<i>${g.total.toLocaleString()}</i></summary>`
               + g.events.map(({ e, n }) => navRow(e, n)).join("")
               + `</details>`;
        }).join("")
      + `</div><div id="nav-eps"></div>`
      // an event page has no other chrome, so the drawer is the only place the
      // attribution can reach someone who deep-linked straight into a story
      + `<div class="nav-attrib">Unofficial fan project. Story text and art are
           © SEGA · Colorful Palette · Crypton Future Media.
           <a href="#/${rangePrefix()}">Full credits</a></div>`;
  }
  for (const a of d.querySelectorAll("#nav-events .nav-ev")) {
    a.classList.toggle("on", a.getAttribute("data-ev") === String(ev.id));
  }
  // Open the group holding the current event, and never close one the reader opened —
  // the list survives navigation, so its expanded state should too.
  for (const g of d.querySelectorAll("#nav-events .nav-grp")) {
    if (g.querySelector(`.nav-ev[data-ev="${ev.id}"]`)) g.setAttribute("open", "");
  }
  el("nav-eps").innerHTML =
    trs.map((tr) => `<details class="nav-grp" open>`
        + `<summary class="nav-h"><span class="nav-t">${tr.oldVersion} → ${tr.newVersion}</span></summary>`
        + tr.episodes.map((ep) => `<a class="nav-ep" data-ep="${epId(tr, ep)}"`
            + ` href="${epHref(ev, tr, ep)}">`
            + `<i>${ep.no}.</i> ${esc(ep.title)} <i>${ep.frames.length}</i></a>`).join("")
        + `</details>`).join("")
    + `<div class="nav-h">All episodes</div>`
    + `<a class="nav-ep" id="expand" href="#">Expand all</a>`
    + `<a class="nav-ep" id="collapse" href="#">Collapse all</a>`;
}

/* ---------- routing ---------- */
// #/                                                          whole window
// #/r/5.4.0.20..5.5.1.20/                                     explicit range
// #/[r/<a>..<b>/]first-star-after-the-rain                    event
// #/…/first-star-after-the-rain/ep03-a-narrow-escape          episode
// #/…/first-star-after-the-rain/ep03-a-narrow-escape/19       one line
//
// ?v=<newVersion> disambiguates the six events rewritten at more than one release —
// three of them repeat an episode number across transitions, so the slug alone is not
// enough. Old ids (e1 / t5_4_0_30-ep03) still resolve: they are in the wild.
function route() {
  const raw = (location.hash || "#/").slice(2);
  const [path, query] = raw.split("?");
  const wantVersion = new URLSearchParams(query || "").get("v") || "";
  const parts = path.split("/").filter(Boolean);
  [view.from, view.to] = spanAll();
  if (parts[0] === "r" && parts[1] && parts[1].includes("..")) {
    parts.shift();
    const [a, b] = parts.shift()!.split("..");
    if (ORDER.has(a) && ORDER.has(b) && pos(a) <= pos(b)) { view.from = a; view.to = b; }
  }
  if (!parts.length) { view.name = "home"; return home(); }
  // reserved segment: checked before the event lookup, and no event slugs to "releases"
  if (parts[0] === "releases") { view.name = "releases"; return releasesPage(); }

  const ev = D.events.find((e) => e.slug === parts[0])
          || D.events.find((e) => "e" + e.id === parts[0]);
  if (!ev || !inRange(ev).length) { view.name = "home"; return home(); }
  view.name = "event";
  // Resolve the episode segment to the DOM id the page actually renders. The slug is
  // per-episode; when a version is given, or the event has only one release, that
  // pins the transition.
  const trs = inRange(ev);
  let domId = "";
  let hitTr: Transition | undefined;
  let hitEp: Episode | undefined;
  if (parts[1]) {
    const byVer = wantVersion ? trs.filter((t) => t.newVersion === wantVersion) : trs;
    for (const t of (byVer.length ? byVer : trs)) {
      const ep = t.episodes.find((x) => x.slug === parts[1]);
      if (ep) { domId = epId(t, ep); hitTr = t; hitEp = ep; break; }
    }
    if (!domId && /^t[\d_]+-ep\d+$/.test(parts[1])) {          // legacy episode id
      domId = parts[1];
      hitTr = trs.find((t) => domId.startsWith("t" + t.newVersion.replace(/\./g, "_")));
      hitEp = hitTr?.episodes.find((x) => epId(hitTr!, x) === domId);
    }
  }
  // Rewrite a legacy or partial URL to the readable one. Old links keep working, but
  // the address bar — and so anything copied out of it — ends up canonical. replaceState
  // does not fire hashchange, so this cannot re-enter route().
  const canonical = hitEp && hitTr
    ? epHref(ev, hitTr, hitEp, parts[2] ? Number(parts[2]) : undefined) : evHref(ev);
  if (location.hash !== canonical) history.replaceState?.(null, "", canonical);
  event(ev, domId);
  if (domId) {
    const section = document.getElementById(domId) as HTMLDetailsElement | null;
    if (section) {
      section.open = true;
      const tr = trs.find((t) => domId.startsWith("t" + t.newVersion.replace(/\./g, "_")));
      const target = parts[2] && tr
        ? document.getElementById(`f-${ev.id}-${tr.newVersion}-${parseInt(domId.slice(-2))}-${parts[2]}`)
        : section;
      setTimeout(() => {
        // optional-call: never let a missing scrollIntoView abort the rest of the route
        (target || section).scrollIntoView?.({ behavior: "smooth", block: parts[2] ? "center" : "start" });
        if (target && target !== section) {
          target.classList.add("flash");
          setTimeout(() => target.classList.remove("flash"), 2200);
        }
      }, 30);
    }
  }
}

const dr = el("drawer"), scrim = el("scrim");
const toggle = (on: boolean) => {
  dr.classList.toggle("open", on); scrim.classList.toggle("open", on);
};
el("burger").onclick = () => toggle(!dr.classList.contains("open"));
scrim.onclick = () => toggle(false);
addEventListener("keydown", (e) => {
  if (e.key === "Escape") toggle(false);
  if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
    const b = document.getElementById("q") || document.getElementById("filter");
    if (b) { e.preventDefault(); b.focus(); }
  }
});
dr.addEventListener("click", (e) => {
  const t = e.target as HTMLElement | null;
  if (!t) return;
  if (t.closest("[data-ep]")) { toggle(false); return; }
  if (t.id === "expand" || t.id === "collapse") {
    e.preventDefault();
    const open = t.id === "expand";
    document.querySelectorAll<HTMLDetailsElement>("main details")
      .forEach((x) => { x.open = open; });
    return;
  }
  if (t.closest("a")) toggle(false);
});
addEventListener("hashchange", route);
// Bundled at build time rather than fetched, so the built site also works when opened
// straight off the filesystem: browsers treat a file:// page as a null origin and
// refuse to fetch a sibling file.
D = payload;
ORDER = new Map(D.versions.map((v, i) => [v.version, i]));
[view.from, view.to] = spanAll();
route();
