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
  const ctx = {
    document, window, console,
    location: { hash },
    setTimeout: (f) => f(),
    addEventListener: (t, f) => { if (t === "hashchange") hashL = f; },
    MutationObserver: class { observe() {} disconnect() {} },
    fetch: () => Promise.resolve({}),
    RegExp, JSON, Math, Object, Array, String, Number, Boolean, Error, Set, Map,
    Event: window.Event,
  };
  ctx.globalThis = ctx;
  vm.createContext(ctx);
  vm.runInContext(js, ctx);
  return { ctx, document, window, nav: (h) => { ctx.location.hash = h; hashL && hashL(); } };
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
  const art = [...b.document.querySelectorAll("#nav-events .nav-art")];
  ok(art.length === withBanner, "every event with banner art shows it in the drawer",
     `${art.length}/${withBanner}`);
  // CSS backgrounds are not lazy; an eager drawer would fetch 38 banners on page load
  ok(art.length > 0 && art.every((i) => i.getAttribute("loading") === "lazy"),
     "drawer banners are lazy");
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
ok(payload.events.every((e) => e.logo), "every event carries a logo",
   `${payload.events.filter((e) => !e.logo).length} missing`);

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
({ document } = boot("#/r/5.4.0.20..5.4.0.30/e1/t5_4_0_30-ep03/19"));
ok(document.getElementById("t5_4_0_30-ep03")?.hasAttribute("open"), "target episode opened");
ok(document.getElementById("f-1-5.4.0.30-3-19"), "target frame present");
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
ok([...document.querySelectorAll("a[href^='#/']")].every((a) =>
     a.getAttribute("href").startsWith("#/r/5.4.0.20..5.4.0.30")),
   "links inside a range keep the range");

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

console.log(`\n${fails === 0 ? "ALL RANGE CHECKS PASSED" : fails + " FAILED"}`);
process.exit(fails ? 1 : 0);
