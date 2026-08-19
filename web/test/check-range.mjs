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

console.log("\nDEEP LINK WITH RANGE");
({ document } = boot("#/r/5.4.0.20..5.4.0.30/e1/t5_4_0_30-ep03/19"));
ok(document.getElementById("t5_4_0_30-ep03")?.hasAttribute("open"), "target episode opened");
ok(document.getElementById("f-1-5.4.0.30-3-19"), "target frame present");
// filenames must be content hashes, or immutable caching would serve stale art
const srcs = [...document.querySelectorAll("main figure img")].map((i) => i.getAttribute("src"));
ok(srcs.length > 0 && srcs.every((u) => /\/[0-9a-f]{16}\.webp$/.test(u)),
   "sprites are content-addressed", srcs[0]);
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
let jpFrames = 0;
for (const e of payload.events) for (const t of e.transitions) for (const ep of t.episodes)
  for (const f of ep.frames) {
    const strip = (h) => h.replace(/<[^>]*>/g, "");
    const ratio = (s) => { const l = [...s].filter((c) => c.trim()); return l.length ? l.filter((c) => JP.test(c)).length / l.length : 0; };
    if (ratio(strip(f.old)) > 0.5 || ratio(strip(f.new)) > 0.5) jpFrames++;
  }
ok(jpFrames === 0, "no Japanese-side lines shown as retranslation", `${jpFrames} found`);

console.log(`\n${fails === 0 ? "ALL RANGE CHECKS PASSED" : fails + " FAILED"}`);
process.exit(fails ? 1 : 0);
