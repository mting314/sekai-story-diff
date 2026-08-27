// Exercises the built bundle in a DOM, without a browser. Assertions are written
// against the *shape* of the data rather than hardcoded totals wherever the corpus
// legitimately grows, so adding events does not produce false failures.
import { parseHTML } from "linkedom";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import vm from "node:vm";

import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../dist");
const html = readFileSync(join(ROOT, "index.html"), "utf8");
const js = readFileSync(join(ROOT, "assets", readdirSync(join(ROOT, "assets")).find((f) => f.endsWith(".js"))), "utf8");
const payload = JSON.parse(readFileSync(resolve(HERE, "../src/data.json"), "utf8"));

function boot(hash = "#/") {
  const { window, document } = parseHTML(html);
  let hashL = null;
  const replaced = [];
  const ctx = {
    document, window, console,
    // records canonicalisation so a test can assert the address bar gets rewritten
    history: { replaceState: (_s, _t, url) => { replaced.push(url); ctx.location.hash = url; } },
    replaced,
    location: { hash },
    setTimeout: (f) => f(),
    addEventListener: (t, f) => { if (t === "hashchange") hashL = f; },
    MutationObserver: class { observe() {} disconnect() {} },
    fetch: () => Promise.resolve({}),
    RegExp, JSON, Math, Object, Array, String, Number, Boolean, Error, Set, Map,
    URLSearchParams,
    Event: window.Event,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  return { ctx, document, window, replaced,
           nav: (h) => { ctx.location.hash = h; hashL && hashL(); } };
}

let fails = 0;
const ok = (c, l, x = "") => { if (!c) fails++; console.log(`${c ? "  PASS" : "  FAIL"}  ${l}${x ? "  " + x : ""}`); };

const EVENTS = payload.events.length;
const FRAMES = payload.events.reduce(
  (n, e) => n + e.transitions.reduce((m, t) => m + t.episodes.reduce((k, ep) => k + ep.frames.length, 0), 0), 0);

console.log(`payload: ${EVENTS} events, ${FRAMES} frames, ${payload.versions.length} versions\n`);

console.log("HOME + RANGE PICKERS");
let { document } = boot("#/");
const from = document.getElementById("from"), to = document.getElementById("to");
ok(from && to, "both version pickers rendered");
ok(from.querySelectorAll("option").length === payload.versions.length,
   `all ${payload.versions.length} live versions offered`, `${from.querySelectorAll("option").length}`);
ok(document.getElementById("allv"), "reset-to-whole-window control");
ok(document.querySelectorAll(".card:not(.soon)").length === EVENTS,
   "every event shown for the full window", `${document.querySelectorAll(".card:not(.soon)").length}/${EVENTS}`);
const tally = document.getElementById("tally").textContent.trim();
ok(tally.includes(`${EVENTS} events`) && /[\d,]+ changed lines/.test(tally), "tally reflects the range", tally);

console.log("\nNARROWING THE RANGE");
({ document } = boot("#/r/5.4.0.20..5.4.0.30/"));
const narrowed = [...document.querySelectorAll(".card:not(.soon) h3")].map((h) => h.textContent.trim());
ok(narrowed.length === 1, "one event in the 5.4.0.20..5.4.0.30 window", narrowed.join(", "));
ok(narrowed[0] === "First Star After the Rain", "and it is the right one", narrowed[0]);
ok(/1 event · 359 changed lines/.test(document.getElementById("tally").textContent),
   "tally counts only in-range lines", document.getElementById("tally").textContent.trim());

console.log("\nRANGE EXCLUDES");
({ document } = boot("#/r/5.2.1.10..5.3.0.0/"));
const early = [...document.querySelectorAll(".card:not(.soon) h3")].map((h) => h.textContent.trim());
ok(!early.includes("First Star After the Rain"), "an out-of-range event is hidden");
ok(early.length > 0 && early.length < EVENTS, "the window has its own, fewer, events",
   `${early.length} of ${EVENTS}`);

console.log("\nMULTI-TRANSITION EVENT");
// an event rewritten at more than one release must show a section per release
const multi = payload.events.find((e) => e.transitions.length > 1);
({ document } = boot(`#/e${multi.id}`));
ok(document.querySelectorAll(".relhdr").length === multi.transitions.length,
   `${multi.name} shows one header per release`,
   `${document.querySelectorAll(".relhdr").length}/${multi.transitions.length}`);
const seen = new Set([...document.querySelectorAll("main .tag")].map((t) => t.textContent.trim()));
const wanted = multi.transitions.flatMap((t) => [`BEFORE ${t.oldVersion}`, `AFTER ${t.newVersion}`]);
ok(wanted.every((w) => seen.has(w)), "each frame tagged with its own transition's versions",
   [...seen].join(" / "));

console.log("\nEVENT PAGE");
({ document } = boot("#/e1"));
ok(document.querySelectorAll("main figure").length === 359, "First Star renders 359 frames",
   `${document.querySelectorAll("main figure").length}`);

console.log("\nDRAWER");
{
  const b = boot("#/e1");
  const rows = [...b.document.querySelectorAll("#nav-events .nav-ev")];
  ok(rows.length === EVENTS, "one drawer row per in-range event", `${rows.length}/${EVENTS}`);
  ok(rows.filter((r) => r.classList.contains("on")).length === 1, "exactly one row marked current");
  ok(b.document.querySelector("#nav-events .nav-ev.on")?.getAttribute("data-ev") === "1",
     "and it is the open event");
  const withBanner = payload.events.filter((e) => e.banner).length;
  const art = [...b.document.querySelectorAll("#nav-events img.nav-art")];
  ok(art.length === withBanner, "every event with banner art shows it in the drawer",
     `${art.length}/${withBanner}`);
  // CSS backgrounds are not lazy; an eager drawer would fetch every banner on page load
  ok(art.length > 0 && art.every((i) => i.getAttribute("loading") === "lazy"),
     "drawer banners are lazy");
  // unit arcs have no banner and fall back to a unit-logo panel of the same size
  const blank = [...b.document.querySelectorAll("#nav-events .nav-art.blank")];
  ok(blank.length === EVENTS - withBanner, "bannerless entries still get an art slot",
     `${blank.length}/${EVENTS - withBanner}`);
  // grouped by unit, heaviest unit first, heaviest event first within each
  const lines = (e) => e.transitions.reduce((n, t) => n + t.changed, 0);
  const byUnit = new Map();
  for (const e of payload.events) {
    const u = e.unit || "mixed";
    byUnit.set(u, (byUnit.get(u) || 0) + lines(e));
  }
  const heads = [...b.document.querySelectorAll("#nav-events .nav-h.unit")];
  ok(heads.length === byUnit.size, "one group header per unit in range",
     `${heads.length}/${byUnit.size}`);
  const wantOrder = [...byUnit.entries()].sort((a, x) => x[1] - a[1]).map(([u]) => u);
  const gotTotals = heads.map((h) => Number(h.querySelector("i").textContent.replace(/,/g, "")));
  ok(gotTotals.every((n, i) => n === byUnit.get(wantOrder[i])),
     "units ordered by total changed lines, descending", gotTotals.join(" > "));
  // rows inside each group descend too; read the counts in document order per group
  let sorted = true;
  for (const h of heads) {
    const got = [];
    for (let s = h.nextElementSibling; s && s.classList.contains("nav-ev"); s = s.nextElementSibling) {
      got.push(Number(s.querySelector("small").textContent.replace(/[^\d]/g, "")));
    }
    if (got.length === 0 || got.some((n, i) => i && n > got[i - 1])) sorted = false;
  }
  ok(sorted, "events within each unit ordered by changed lines, descending");
  // the logo now sits on the group header, once per unit, not on every row
  const wantLogos = new Set(payload.events.filter((e) => e.unitLogo).map((e) => e.unit)).size;
  ok(b.document.querySelectorAll("#nav-events .nav-ulogo").length === wantLogos,
     "one unit logo per group that has one", `${wantLogos} expected`);
  // the drawer must obey the range like everything else
  const nb = boot("#/r/5.4.0.20..5.4.0.30/e1");
  ok(nb.document.querySelectorAll("#nav-events .nav-ev").length === 1,
     "a narrowed range narrows the drawer too",
     `${nb.document.querySelectorAll("#nav-events .nav-ev").length}`);
  ok(nb.document.querySelectorAll("#nav-events .nav-h.unit").length === 1,
     "and drops the units that have nothing in it",
     `${nb.document.querySelectorAll("#nav-events .nav-h.unit").length}`);
}

console.log("\nMAGNITUDE");
const LABELS = ["retranslation", "revised", "punctuation"];
const labels = payload.events.flatMap((e) => e.transitions.map((t) => t.label));
ok(labels.length > 0 && labels.every((l) => LABELS.includes(l)),
   "every transition carries a known label",
   [...new Set(labels)].join(", "));
const named = (n) => payload.events.find((e) => e.name.startsWith(n));
for (const [name, want] of [["First Star", "retranslation"], ["Imprisoned Marionette", "retranslation"],
                            ["Wonder Magical Showtime", "punctuation"], ["Screaming?!", "punctuation"]]) {
  const ev = named(name);
  ok(ev && ev.transitions.some((t) => t.label === want),
     `${name} reads as ${want}`, ev ? ev.transitions.map((t) => t.label).join(",") : "not found");
}
ok(payload.events.every((e) => e.transitions.every((t) => t.breadth <= 1)),
   "no event reports breadth over 100%");
({ document } = boot("#/"));
ok(document.querySelector(".card .pill.mag"), "badge rendered on the home card",
   document.querySelector(".card .pill.mag")?.textContent);

console.log("\nEVENT HEADER");
({ document } = boot("#/e1"));
{
  const bar = document.querySelector(".topbar");
  const logo = bar.querySelector(".elogo");
  ok(logo, "header shows the event's own title art");
  ok(logo?.getAttribute("src").endsWith("logo/event_stella_2020.webp"),
     "and it is this event's logo, not the unit's", logo?.getAttribute("src"));
  ok(!bar.querySelector(".ulogo"), "the unit logo is gone from the header");
  ok(!bar.querySelector(".pill.mag"), "the magnitude chip is gone from the header");
  ok(bar.querySelector("h2").textContent.trim() === "First Star After the Rain",
     "the event name is still the accessible label");
}
// arcs have no title art on the mirror; every real event does
ok(payload.events.filter((e) => e.kind !== "arc").every((e) => e.logo),
   "every event carries a logo",
   `${payload.events.filter((e) => e.kind !== "arc" && !e.logo).length} missing`);

console.log("\nLINES EDITED TWICE");
{
  // find them in the payload independently of the app, so the test is not just asserting
  // that the implementation agrees with itself
  const plain = (h) => h.replace(/<[^>]*>/g, "")
    .replace(/&(?:amp|lt|gt|quot|#x27);/g,
             (m) => ({ "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&#x27;": "'" }[m]));
  const order = new Map(payload.versions.map((v, i) => [v.version, i]));
  const chains = [];
  for (const e of payload.events) {
    const by = new Map();
    for (const t of e.transitions) for (const ep of t.episodes) for (const f of ep.frames) {
      const k = `${ep.no}|${f.talkIndex}`;
      by.set(k, [...(by.get(k) || []), { t, ep, f }]);
    }
    for (const [k, hits] of by) {
      if (hits.length < 2) continue;
      hits.sort((a, b) => order.get(a.t.newVersion) - order.get(b.t.newVersion));
      chains.push({ e, k, hits });
    }
  }
  ok(chains.length > 0, `${chains.length} line(s) were edited at more than one release`);
  // the finding this exists to surface: every one of them nets to nothing
  const reverts = chains.filter(({ hits }) =>
    plain(hits[0].f.old) === plain(hits[hits.length - 1].f.new)
    && hits[0].f.speakerOld === hits[hits.length - 1].f.speaker);
  ok(reverts.length === chains.length, "and all of them are reverts that end unchanged",
     `${reverts.length}/${chains.length}`);

  const { e, hits } = chains[0];
  const b = boot(`#/${e.slug}`);
  const notes = [...b.document.querySelectorAll("main .again")];
  // one note per occurrence, on every frame in the chain, in this event
  const inThisEvent = chains.filter((c) => c.e.id === e.id)
    .reduce((n, c) => n + c.hits.length, 0);
  ok(notes.length === inThisEvent, "each occurrence is flagged",
     `${notes.length}/${inThisEvent}`);
  ok(notes[0].textContent.includes("also edited at"), "the note says so",
     notes[0].textContent.replace(/\s+/g, " ").trim());
  ok(/ends unchanged/.test(notes[0].textContent), "and that the chain nets to nothing");

  // the note must point at the *other* occurrence, not itself, and that link must work
  const href = notes[0].querySelector("a").getAttribute("href");
  const otherVersions = hits.map((h) => h.t.newVersion);
  ok(otherVersions.some((v) => href.includes(v)), "linking to a release in the chain", href);
  const nb = boot(href);
  ok(nb.document.querySelectorAll("main figure").length > 0,
     "and that link opens the event", href);
  // an explicit range, so it resolves even when the other edit is outside the current one
  ok(href.startsWith("#/r/"), "with a range that makes it resolve from anywhere", href);

  // a line edited once must not be flagged, or the marker means nothing
  const single = boot("#/e1");
  ok(single.document.querySelectorAll("main .again").length === 0,
     "an event with one release flags nothing",
     `${single.document.querySelectorAll("main .again").length}`);
}

console.log("\nSPEAKER-ONLY CHANGES");
{
  // some frames change only the name plate; with the name unmarked the before/after
  // pair reads as two identical frames and the edit is invisible
  const strip2 = (h) => h.replace(/<[^>]*>/g, "");
  const renamed = payload.events.flatMap((e) => e.transitions.flatMap((t) =>
    t.episodes.flatMap((ep) => ep.frames
      .filter((f) => f.speakerOld && f.speakerOld !== f.speaker)
      .map((f) => ({ e, t, ep, f })))));
  ok(renamed.length > 0, `${renamed.length} frame(s) change the speaker name`);
  const silent = renamed.filter(({ f }) => strip2(f.old) === strip2(f.new));
  ok(silent.length > 0,
     `${silent.length} of them change nothing else, so the name is the only signal`);

  const { e, f } = silent[0];
  const b = boot(`#/${e.slug}`);
  const fig = [...b.document.querySelectorAll("main figure")]
    .find((x) => x.getAttribute("id").endsWith(`-${f.talkIndex}`));
  ok(fig, "the frame renders");
  ok(fig.querySelector(".spk.old b") && fig.querySelector(".spk.new b"),
     "a renamed speaker is marked on both sides",
     fig.querySelector(".spk.old b")?.textContent + " -> "
     + fig.querySelector(".spk.new b")?.textContent);
  // and an unchanged speaker must NOT be marked, or the highlight means nothing
  const plain = payload.events[0].transitions[0].episodes[0].frames
    .find((x) => !x.speakerOld || x.speakerOld === x.speaker);
  const pf = [...b.document.querySelectorAll("main figure .spk")]
    .filter((s) => !s.classList.contains("old") && !s.classList.contains("new"));
  ok(plain && pf.length > 0, "unchanged speakers are left unmarked", `${pf.length} plain`);
}

console.log("\nRELEASE BROWSER");
{
  const b = boot("#/releases");
  const rows = [...b.document.querySelectorAll(".rel")];
  const pairs = payload.versions.length - 1;
  ok(rows.length === pairs, "one row per adjacent release pair", `${rows.length}/${pairs}`);

  // reconcile against the payload rather than against a hardcoded number
  const byPair = new Map();
  for (const e of payload.events) for (const t of e.transitions) {
    const k = `${t.oldVersion}..${t.newVersion}`;
    byPair.set(k, (byPair.get(k) || 0) + t.changed);
  }
  const live = rows.filter((r) => !r.classList.contains("quiet"));
  ok(live.length === byPair.size, "every release that changed something gets a full row",
     `${live.length}/${byPair.size}`);
  ok(rows.length - live.length === pairs - byPair.size,
     "and the rest are marked as having changed nothing",
     `${rows.length - live.length} quiet`);

  // line counts must equal the payload's, not be recomputed loosely
  const shown = live.reduce((n, r) =>
    n + Number((r.querySelector(".rel-n").textContent.match(/([\d,]+) line/) || [0, 0])[1]
      .toString().replace(/,/g, "")), 0);
  const want = [...byPair.values()].reduce((a, x) => a + x, 0);
  ok(shown === want, "release line counts reconcile with the payload", `${shown} vs ${want}`);

  // the busiest release should be First Star's, and its row must name it
  const top = live[live.findIndex((r) => /5\.4\.0\.20 → 5\.4\.0\.30/.test(r.textContent))];
  ok(top, "the First Star release is listed");
  ok(/359/.test(top.textContent), "with its line count", top.textContent.replace(/\s+/g, " ").trim());
  const chips = top.nextElementSibling;
  ok(chips && chips.classList.contains("rel-evs")
     && /First Star After the Rain/.test(chips.textContent),
     "and the events it touched", chips?.textContent.replace(/\s+/g, " ").trim().slice(0, 50));
  // the magnitude belongs on the event tile, not the release header: a release touching
  // eight events has no single magnitude, and showing both said it twice
  ok(!top.querySelector(".pill.mag"), "the release header carries no magnitude chip");
  ok(chips.querySelector(".rel-ev .pill.mag"), "each event tile carries its own",
     chips.querySelector(".rel-ev .pill.mag")?.textContent);
  ok(chips.querySelector(".rel-ev img.rel-art, .rel-ev .rel-art.blank"),
     "and its banner art");

  // every row links into the range view, which is what actually renders the detail
  const href = top.getAttribute("href");
  ok(href === "#/r/5.4.0.20..5.4.0.30/", "a release links to its range", href);
  const rb = boot(href);
  ok(rb.document.querySelectorAll(".card:not(.soon)").length === 1,
     "and that range renders exactly the events it claims",
     `${rb.document.querySelectorAll(".card:not(.soon)").length}`);
  // an event chip deep-links straight into that event, scoped to the release
  const chip = chips.querySelector("a.rel-ev").getAttribute("href");
  ok(chip === "#/r/5.4.0.20..5.4.0.30/first-star-after-the-rain",
     "an event chip links into the event within that release", chip);
  ok(boot(chip).document.querySelectorAll("main figure").length === 359,
     "and that link opens the event");

  ok(b.document.getElementById("burger").hasAttribute("hidden"),
     "the drawer button is hidden — there is no event to scope it to");
  // reachable from both other views
  ok(boot("#/").document.querySelector("a[href='#/releases']"), "home links to releases");
  ok(boot("#/e1").document.querySelector("#drawer a[href='#/releases']"),
     "the drawer links to releases");
}

console.log("\nATTRIBUTION");
{
  const b = boot("#/");
  const foot = b.document.querySelector(".attrib");
  ok(foot, "home carries an attribution footer");
  const txt = foot.textContent.replace(/\s+/g, " ");
  for (const who of ["SEGA", "Colorful Palette", "Crypton Future Media"]) {
    ok(txt.includes(who), `names ${who} as a rights holder`);
  }
  ok(/unofficial fan project/i.test(txt) && /not affiliated/i.test(txt),
     "says plainly that it is unofficial and unaffiliated");
  // the pipeline depends on these; they should be credited, not silently consumed
  for (const src of ["sekai-master-db-en-diff", "sekai.best", "sssekai",
                     "sekai-viewer", "Cleista"]) {
    ok(txt.includes(src), `credits ${src}`);
  }
  ok([...foot.querySelectorAll("a")].every((a) =>
       a.getAttribute("rel") === "noopener noreferrer"),
     "every outbound credit link is safe");

  // an event page has no footer, so the drawer has to carry it
  const e = boot("#/e1");
  const nav = e.document.querySelector(".nav-attrib");
  ok(nav, "the drawer carries a short attribution too");
  ok(/SEGA/.test(nav.textContent) && nav.querySelector("a[href^='#/']"),
     "with the rights holders and a link back to the full credits",
     nav.textContent.replace(/\s+/g, " ").trim().slice(0, 60));
}

console.log("\nREAD-IN-CONTEXT LINKS");
{
  // every episode needs the game's scenario id and every entry its bundle name, or the
  // link cannot be built at all
  ok(payload.events.every((e) => e.bundleName), "every entry carries its bundle name",
     `${payload.events.filter((e) => !e.bundleName).length} missing`);
  const eps = payload.events.flatMap((e) => e.transitions.flatMap((t) => t.episodes));
  ok(eps.every((ep) => ep.scenarioId), "every episode carries its scenario id",
     `${eps.filter((ep) => !ep.scenarioId).length} missing`);
  // arcs must use the unit path and the chapter bundle, not "unitstory"
  const arc = payload.events.find((e) => e.kind === "arc");
  ok(arc && /-story-chapter$/.test(arc.bundleName),
     "an arc's bundle name is its chapter, not the literal 'unitstory'", arc?.bundleName);

  const b = boot("#/e1");
  const link = b.document.querySelector("main figcaption a.ctx");
  ok(link, "each frame offers a read-in-context link");
  const href = link.getAttribute("href");
  ok(href.startsWith("https://pjsk.cleista.cc/#/read/event/event_stella_2020/event_"),
     "event links use the event path and bundle", href);
  // ?line counts the reader's steps, not TalkData — telops are steps too — so it must
  // come from readerLine and must NOT be our line number. Asserting equality is what
  // shipped every link on the wrong line the first time.
  ok(payload.events.every((e) => e.transitions.every((t) => t.episodes.every((ep) =>
       ep.frames.every((f) => Number.isInteger(f.readerLine) && f.readerLine >= 1)))),
     "every frame carries a reader line");
  const drift = payload.events.flatMap((e) => e.transitions.flatMap((t) =>
    t.episodes.flatMap((ep) => ep.frames.map((f) => f.readerLine - f.talkIndex))));
  ok(drift.every((d) => d >= 0), "a reader line is never behind our line number",
     `min ${Math.min(...drift)}`);
  ok(drift.some((d) => d > 0), "and runs ahead where telops precede the line",
     `${drift.filter((d) => d > 0).length} of ${drift.length} frames drift`);
  // spot-check the one line verified by hand against the live reader
  const stella = payload.events.find((e) => e.id === 1);
  const ep1 = stella.transitions.flatMap((t) => t.episodes).find((ep) => ep.no === 1);
  const f25 = ep1.frames.find((f) => f.talkIndex === 25);
  ok(f25 && f25.readerLine === 26,
     "First Star ep1 #25 maps to ?line=26, as confirmed in the live reader",
     `readerLine ${f25?.readerLine}`);
  const fig = link.closest("figure");
  const ours = Number(fig.getAttribute("id").split("-").pop());
  const sent = Number(new URL(href.replace("#/", "")).searchParams.get("line"));
  ok(sent >= ours, "the emitted link uses the reader's numbering", `#${ours} -> ?line=${sent}`);
  ok(link.getAttribute("rel") === "noopener noreferrer" && link.getAttribute("target") === "_blank",
     "outbound link opens safely in a new tab");

  const ab = boot(`#/e${arc.id}`);
  const ahref = ab.document.querySelector("main figcaption a.ctx").getAttribute("href");
  ok(ahref.includes("/read/unit/"), "arc links use the unit path", ahref);
}

console.log("\nLINE NUMBERING");
{
  // 1-based: "#34" should be the 34th line, not the 35th. The payload is the boundary
  // where an array offset becomes a line number, so nothing downstream adds or
  // subtracts one — a regression here would silently shift every deep link by a line,
  // landing on adjacent dialogue that looks plausible rather than obviously wrong.
  const idx = payload.events.flatMap((e) => e.transitions.flatMap((t) =>
    t.episodes.flatMap((ep) => ep.frames.map((f) => f.talkIndex))));
  ok(Math.min(...idx) === 1, "line numbers start at 1", `min ${Math.min(...idx)}`);
  ok(idx.every((n) => Number.isInteger(n) && n >= 1), "and are all positive integers");
  // every episode's own numbering must start at or above 1 too
  const perEp = payload.events.flatMap((e) => e.transitions.flatMap((t) =>
    t.episodes.map((ep) => Math.min(...ep.frames.map((f) => f.talkIndex)))));
  ok(perEp.every((n) => n >= 1), "no episode carries a zero line", `min ${Math.min(...perEp)}`);

  const b = boot("#/e1");
  const cap = b.document.querySelector("main figcaption").textContent.trim();
  ok(/^#[1-9]/.test(cap), "the caption shows a 1-based number", cap.split("\n")[0]);
}

console.log("\nENTITY DECODING");
{
  // the payload is HTML: html.escape() turned ' into &#x27; and < into &lt;
  const raw = payload.events.flatMap((e) => e.transitions.flatMap((t) =>
    t.episodes.flatMap((ep) => ep.frames.flatMap((f) => [f.old, f.new]))));
  const withEntities = raw.filter((s) => /&(amp|lt|gt|quot|#x27);/.test(s));
  ok(withEntities.length > 0, "the payload really does carry HTML entities",
     `${withEntities.length} of ${raw.length} lines`);

  const b = boot("#/");
  const box = b.document.getElementById("q");
  // a query that only matches through an apostrophe — this used to find nothing at all
  box.value = "can't find it"; box.dispatchEvent(new b.window.Event("input"));
  const hits = [...b.document.querySelectorAll(".hit")];
  ok(hits.length > 0, "a query containing an apostrophe finds its line", `${hits.length} hit(s)`);
  const shown = hits.map((h) => h.textContent).join(" ");
  ok(!/&(amp|lt|gt|quot|#x27);/.test(shown),
     "and no raw entity is printed in the result",
     (shown.match(/&\w+;|&#x27;/) || ["clean"])[0]);
  ok(shown.includes("can't"), "the apostrophe renders as an apostrophe");

  // angle brackets are used for the game's whispered lines; they must not leak either
  const b2 = boot("#/");
  const q2 = b2.document.getElementById("q");
  q2.value = "I didn't hate it"; q2.dispatchEvent(new b2.window.Event("input"));
  const t2 = [...b2.document.querySelectorAll(".hit")].map((h) => h.textContent).join(" ");
  ok(!/&(amp|lt|gt|quot|#x27);/.test(t2), "whispered <…> lines render their brackets",
     (t2.match(/&\w+;|&#x27;/) || ["clean"])[0]);
}

console.log("\nREADABLE URLS");
{
  const first = payload.events.find((e) => e.name === "First Star After the Rain");
  ok(first.slug === "first-star-after-the-rain", "event slug reads as the event name",
     first.slug);
  ok(payload.events.every((e) => /^[a-z0-9-]+$/.test(e.slug)), "all event slugs are clean");
  ok(new Set(payload.events.map((e) => e.slug)).size === payload.events.length,
     "and unique — a duplicate would make one entry unreachable");
  const eps = payload.events.flatMap((e) => e.transitions.flatMap((t) => t.episodes));
  ok(eps.every((ep) => /^ep\d\d(-[a-z0-9-]+)?$/.test(ep.slug)),
     "episode slugs lead with the number and carry the title",
     eps[0].slug);

  // the readable URL resolves
  let b = boot(`#/${first.slug}/${first.transitions[0].episodes[2].slug}/19`);
  ok(b.document.querySelectorAll("main figure").length === 359, "slug URL opens the event");
  ok([...b.document.querySelectorAll("main details[open]")].length === 1,
     "and opens exactly the named episode",
     [...b.document.querySelectorAll("main details[open]")].map((x) => x.id).join(","));

  // old links are in the wild and must keep working
  b = boot("#/e1/t5_4_0_30-ep03/19");
  ok(b.document.querySelectorAll("main figure").length === 359, "legacy e<id> URL still resolves");
  ok(b.document.getElementById("t5_4_0_30-ep03")?.hasAttribute("open"),
     "legacy episode id still opens");
  // ...but the address bar must end up canonical, so anything copied out of it is good
  ok(b.replaced.length === 1 && b.replaced[0] === `#/${first.slug}/ep03-less-stars-more-bass/19`,
     "a legacy URL is rewritten to the readable one", b.replaced.join(" "));
  b = boot("#/e157");
  ok(b.replaced[0] === "#/rise-and-strive", "a bare legacy event id is rewritten too",
     b.replaced.join(" "));
  // and a URL that is already canonical must not be rewritten at all
  b = boot(`#/${first.slug}`);
  ok(b.replaced.length === 0, "an already-readable URL is left alone", b.replaced.join(" "));

  // an event rewritten twice needs ?v= to say which release
  const multi = payload.events.find((e) => e.transitions.length > 1);
  const mt = multi.transitions[1], mep = mt.episodes[0];
  b = boot(`#/${multi.slug}/${mep.slug}?v=${mt.newVersion}`);
  const open = [...b.document.querySelectorAll("main details[open]")].map((x) => x.id);
  ok(open.length === 1 && open[0].startsWith("t" + mt.newVersion.replace(/\./g, "_")),
     `?v= picks the right release for ${multi.name}`, open.join(","));

  // links the page emits must round-trip through the router
  b = boot("#/");
  const box = b.document.getElementById("q");
  box.value = "bass"; box.dispatchEvent(new b.window.Event("input"));
  const hit = b.document.querySelector(".hit");
  ok(hit, "search produces a hit to test");
  const href = hit.getAttribute("href");
  ok(/^#\/[a-z0-9-]+\/ep\d\d/.test(href), "search hits link to a readable URL", href);
  // this used to emit #/e1/ep03/19 — an id no element has — so the episode never opened
  const hb = boot(href);
  ok([...hb.document.querySelectorAll("main details[open]")].length === 1,
     "and that link actually opens its episode",
     [...hb.document.querySelectorAll("main details[open]")].map((x) => x.id).join(","));
}

console.log("\nDIALOGUE OVERLAY");
{
  const b = boot("#/e1");
  const fig = b.document.querySelector("main figure");
  ok(!b.document.querySelector(".box"), "the opaque white dialogue box is gone");
  const dlg = fig.querySelectorAll(".dlg");
  ok(dlg.length === 2, "each frame has a before and an after overlay", `${dlg.length}`);
  // it must be inside the stage: that is what makes cqmin resolve against the stage
  // box rather than the card, and what puts it over the art instead of beside it
  ok([...dlg].every((d) => d.closest(".stage")), "the overlay sits inside the stage");
  ok([...fig.querySelectorAll(".stage")].every((s) => s.querySelector(".dlg")),
     "and every stage carries one");
  ok(fig.querySelector(".spk-row .spk") && fig.querySelector(".spk-row .spk-rule"),
     "speaker row has a name and its underline rule");
  ok(fig.querySelectorAll(".tag.o").length === 1 && fig.querySelectorAll(".tag.n").length === 1,
     "before/after version tags survive the restyle");
  // the diff highlight is the whole point of the frame; it must still be marked up
  const marked = fig.querySelectorAll(".txt.old b, .txt.new b");
  ok(marked.length > 0, "diff spans still render inside the overlay text",
     `${marked.length} span(s)`);
}

console.log("\nUNIT ARCS");
{
  const arcs = payload.events.filter((e) => e.kind === "arc");
  ok(arcs.length > 0, `${arcs.length} unit arc(s) in the payload`);
  // the whole point of the pseudo-event model: ids must not collide with real events
  const evIds = new Set(payload.events.filter((e) => e.kind !== "arc").map((e) => e.id));
  ok(arcs.every((a) => !evIds.has(a.id)), "arc ids do not collide with event ids",
     arcs.map((a) => a.id).join(","));
  ok(arcs.every((a) => a.unit && a.unitLogo && a.colour !== "#8f89b5"),
     "arcs resolve their unit colour and logo",
     arcs.map((a) => `${a.unit}:${a.colour}`).join(" "));
  ok(arcs.every((a) => a.shortName), "arcs carry a short label for the drawer",
     arcs.map((a) => a.shortName).join(" / "));
  // an arc must be reachable and render like any other entry
  const ab = boot(`#/e${arcs[0].id}`);
  ok(ab.document.querySelectorAll("main figure").length > 0,
     `${arcs[0].name} renders frames`,
     `${ab.document.querySelectorAll("main figure").length}`);
  ok(ab.document.querySelector(".topbar .ulogo"),
     "arc header falls back to the unit logo");
  ok(!ab.document.querySelector(".topbar .elogo"), "and has no event title art");
  // and it must group under its unit in the drawer, not in a bucket of its own
  const grp = [...ab.document.querySelectorAll("#nav-events .nav-grp")]
    .find((g) => g.querySelector(`.nav-ev[data-ev="${arcs[0].id}"]`));
  ok(grp && grp.querySelectorAll(".nav-ev").length > 1,
     "the arc sits in its unit's group alongside that unit's events",
     `${grp?.querySelectorAll(".nav-ev").length} rows`);
}

console.log("\nEMPTY FILTER");
{
  const b = boot("#/e1");
  const f = b.document.getElementById("filter");
  f.value = "zzzznothingmatches";
  f.oninput();
  const msg = b.document.getElementById("nomatch");
  ok(msg && msg.textContent.length > 0, "filter with no matches explains itself",
     msg ? msg.textContent : "(no element)");
}

console.log("\nDEEP LINK WITH RANGE");
({ document } = boot("#/r/5.4.0.20..5.4.0.30/e1/t5_4_0_30-ep03/20"));
ok(document.getElementById("t5_4_0_30-ep03")?.hasAttribute("open"), "target episode opened");
ok(document.getElementById("f-1-5.4.0.30-3-20"), "target frame present");
// filenames must be content hashes, or immutable caching would serve stale art
const srcs = [...document.querySelectorAll("main figure img")].map((i) => i.getAttribute("src"));
ok(srcs.length > 0 && srcs.every((u) => /\/[0-9a-f]{16}\.webp$/.test(u)),
   "sprites are content-addressed", srcs[0]);
// Generated media is not in the repo any more, so a relative sprite URL means
// VITE_ASSET_BASE did not reach the build and every image will 404.
const expectBase = process.env.EXPECT_ASSET_BASE;
if (expectBase) {
  ok(srcs.every((u) => u.startsWith(expectBase)),
     `sprites point at ${expectBase}`, srcs[0]);
}
// #/releases is deliberately exempt: it is the view you use to *pick* a range, so
// carrying the current one into it would be backwards. Everything else must keep it.
ok([...document.querySelectorAll("a[href^='#/']")]
     .filter((a) => a.getAttribute("href") !== "#/releases")
     .every((a) => a.getAttribute("href").startsWith("#/r/5.4.0.20..5.4.0.30")),
   "links inside a range keep the range");
ok(document.querySelector("a[href='#/releases']"),
   "except the release browser, which is how you leave a range");

console.log("\nSEARCH RESPECTS RANGE");
let b = boot("#/r/5.4.0.20..5.4.0.30/");
let box = b.document.getElementById("q");
box.value = "bass"; box.dispatchEvent(new b.window.Event("input"));
ok(b.document.querySelectorAll(".hit").length > 0, "finds a line inside the range");
b = boot("#/r/5.2.1.10..5.3.0.0/");
box = b.document.getElementById("q");
box.value = "bass"; box.dispatchEvent(new b.window.Event("input"));
ok(b.document.querySelectorAll(".hit").length === 0, "same query finds nothing outside it",
   `${b.document.querySelectorAll(".hit").length} hits`);

console.log("\nLANGUAGE FLIPS EXCLUDED");
// 71% of catalogue changes are a first localisation, not a rewrite; none may appear
const JP = /[぀-ヿ一-鿿]/;
const strip = (h) => h.replace(/<[^>]*>/g, "");
// letters only: counting punctuation is what let 'ん…………' -> 'Mm...' pass as a rewrite
const letters = (s) => [...s].filter((c) => /[\p{L}\p{N}]/u.test(c));
const jpRatio = (s) => { const l = letters(s); return l.length ? l.filter((c) => JP.test(c)).length / l.length : 0; };
let jpFrames = 0, punctOnly = 0;
for (const e of payload.events) for (const t of e.transitions) for (const ep of t.episodes)
  for (const f of ep.frames) {
    const o = strip(f.old), n = strip(f.new);
    if (jpRatio(o) > 0.5 || jpRatio(n) > 0.5) jpFrames++;
    if (!letters(o).length && !letters(n).length) punctOnly++;
  }
ok(jpFrames === 0, "no Japanese-side lines shown as retranslation", `${jpFrames} found`);
ok(punctOnly === 0, "no punctuation-only lines shown as retranslation", `${punctOnly} found`);

console.log("\nPAYLOAD MATCHES ITS DECLARED TYPE");
{
  // payload.d.ts is hand-written, so nothing structurally stops it drifting from what
  // build_web_gallery.py emits. This reads the declarations themselves rather than
  // restating them here — a third copy of the shape would drift from both — and checks
  // the real payload against them. tsc validates main.ts against the .d.ts; this
  // validates the .d.ts against reality, and together they close the loop.
  const dts = readFileSync(resolve(HERE, "../src/payload.d.ts"), "utf8");
  const ifaces = new Map();
  for (const m of dts.matchAll(/export interface (\w+) \{([^}]*)\}/g)) {
    const fields = [...m[2].matchAll(/^\s*(\w+)(\??):\s*([^;]+);/gm)]
      .map((f) => ({ name: f[1], optional: f[2] === "?", type: f[3].trim() }));
    ifaces.set(m[1], fields);
  }
  ok(ifaces.size >= 10, `parsed ${ifaces.size} interfaces from payload.d.ts`);

  const ev = payload.events[0];
  const tr = ev.transitions[0];
  const epi = tr.episodes[0];
  const frame = tr.episodes.flatMap((x) => x.frames).find((f) => f.layers.length);
  const samples = [
    ["Payload", [payload]],
    ["Comparison", [payload.comparison]],
    ["EventEntry", payload.events],
    ["Transition", payload.events.flatMap((e) => e.transitions)],
    ["Episode", [epi]],
    ["Frame", [frame, tr.episodes[0].frames[0]]],
    ["Layer", frame.layers],
    ["Sprite", Object.values(payload.sprites).slice(0, 50)],
    ["Version", payload.versions],
    ["PendingEvent", payload.pending],
    ["Dropped", payload.dropped],
  ];
  for (const [name, objs] of samples) {
    const declared = ifaces.get(name);
    if (!declared) { ok(false, `payload.d.ts declares ${name}`); continue; }
    if (!objs.length) {
      // empty in this build, so there is nothing to compare against — say so rather
      // than let a vacuous pass look like coverage
      console.log(`  ----  ${name}: none in this payload, shape unverified`);
      continue;
    }
    const want = new Set(declared.filter((f) => !f.optional).map((f) => f.name));
    const allowed = new Set(declared.map((f) => f.name));
    const missing = new Set(), extra = new Set();
    for (const o of objs) {
      for (const k of want) if (!(k in o)) missing.add(k);
      for (const k of Object.keys(o)) if (!allowed.has(k)) extra.add(k);
    }
    ok(missing.size === 0 && extra.size === 0,
       `${name} matches (${objs.length} sampled)`,
       [...(missing.size ? [`missing ${[...missing]}`] : []),
        ...(extra.size ? [`undeclared ${[...extra]}`] : [])].join(" "));
  }

  // the union members have to be exhaustive, or a new one arrives typed as impossible
  const unions = {
    "events[].kind": [payload.events.map((e) => e.kind), /"event" \| "arc"/],
    "transitions[].label": [payload.events.flatMap((e) => e.transitions.map((t) => t.label)),
                            /Magnitude =([^;]+);/],
    "frames[].cover": [payload.events.flatMap((e) => e.transitions.flatMap((t) =>
                         t.episodes.flatMap((x) => x.frames.map((f) => f.cover)))),
                       /Cover =([^;]+);/],
  };
  for (const [what, [values, pattern]] of Object.entries(unions)) {
    const src = pattern.source.includes("=") ? (dts.match(pattern) || [, ""])[1] : pattern.source;
    const declared = new Set([...src.matchAll(/"([^"]*)"/g)].map((m) => m[1]));
    const seen = new Set(values);
    const rogue = [...seen].filter((v) => !declared.has(v));
    ok(rogue.length === 0, `${what} only holds declared values`,
       rogue.length ? `undeclared: ${rogue}` : `${[...seen].map((v) => `"${v}"`).join(", ")}`);
  }
}

console.log(`\n${fails === 0 ? "ALL RANGE CHECKS PASSED" : fails + " FAILED"}`);
process.exit(fails ? 1 : 0);
