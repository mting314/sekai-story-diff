# Backlog

Ordered roughly by how much they unblock or how visible they are. Each entry says what
it is, why it matters, and what makes it non-trivial — the last part is the bit worth
knowing before picking one up.

---

## 1. Bilingual mode

Show the Japanese alongside the English on the stage, the way Cleista's reader does
(`#/read/event/event_stella_2020/event_01_01?line=3`). Its dialogue overlay becomes a
two-column grid when a second language is on — `.reader.has-secondary .dialogue-overlay
{ grid-template-columns: 1fr 1fr }` — collapsing to one column when narrow, with the
script list below repeating the pairing row by row.

**Why:** the JP line is the thing both English versions are translating, so it is the
only way to judge which one is *better* rather than merely different. We already carry
it on every frame (`f.jp`, 100% coverage since the unit-arc fix), but it sits in the
figcaption under the pair, detached from the art and easy to miss.

**Watch out for:** our frame is a before/after pair and the JP is the same for both, so
their layout does not port directly — duplicating it in each overlay is wrong and putting
it in only one is lopsided. A third full-width row under the pair, styled like the
overlay rather than like a caption, is probably the honest shape.

Also: the overlay is already carrying a speaker row, a BEFORE/AFTER tag and the line at
`clamp(10.5px, 4.6cqmin, 17px)`. Their stage runs to 940px; a card in our grid is ~540px
and ~366px on a phone, so a second column may simply not fit and this may have to be
stack-only. Worth a mock at card width before committing to it.

It should be a toggle, not always-on — they treat it as a mode (`reader/languages.js`,
`translate-mode.js`). That means persistence, and `check-range.mjs` has no localStorage
stub yet. No pipeline work either way: the data is already in the payload.

**Not in scope:** furigana. Their reader renders it (`.furigana-always rt`) but that
needs per-token readings we do not have and would not get from the scenario data.

---

## 2. Flag lines that were edited twice

A line can be changed at one release and changed again at a later one. The event page
shows both, one section per release, but never composes them: a line that went A→B then
B→C is shown as A→B and B→C, never as A→C.

**Why it is worth surfacing:** every instance in the corpus is a *revert*. All five of
them net to no change at all.

    An Ode for the Pure of Heart · ep7 #1
      4.1.50.20 → 4.1.51.0   "everything dad asked me to do"  →  "Dad"
      5.3.50.0  → 5.3.51.0   "Dad"  →  "dad"

    Nightcord at 25:00, Chapter 1 · ep6 #25–28   (speaker only, body identical)
      4.1.50.20  → 4.1.51.0    Kanade's Father  →  Kanade's Dad
      4.1.51.10  → 4.1.51.15   Kanade's Dad     →  Kanade's Father

Someone capitalised *Dad* and reverted it fifteen releases later; someone renamed a
speaker and reverted it two releases later. That is a real editorial signal and the site
currently makes you find it by hand.

**Watch out for the framing.** The obvious feature is "net diff across a version range",
but a net-diff view over this corpus would render five empty results — the composition
is a no-op in every case. The value is the *observation*, not the diff. Build it as a
flag on the frame ("edited again at 5.3.51.0, back to its original wording") linking to
the other occurrence, not as a new view.

**Cheap:** no pipeline work. Group frames by (event, episode no, talkIndex) across
transitions in `main.js` — 1,107 frames, and only 5 land in a group larger than one.
Six events have more than one transition, so the scan is small and bounded.

---

## Done

- Web app on TypeScript. `tsc --noEmit` in CI *before* the build, which is the whole
  point — Vite strips types with esbuild and never checks them, so without that step the
  migration would have been decorative. Payload shape hand-written in `src/payload.d.ts`
  and kept honest by a drift check that parses the declarations and walks the real
  payload against them; branded `Html` / `LineNo` / `ReaderNo` catch the right-type
  wrong-meaning confusions that plain interfaces cannot
- Version browser at `#/releases` — every release in the live window, what each changed,
  and the 18 that changed nothing kept in place. Derived in the browser from 46
  transitions, not the 1,107 frames under them, so no payload or pipeline change
- Dialogue styled like the game: the opaque white card replaced by the two stacked
  gradients and #fff text stroked in #4a4968, sized in `cqmin` against the stage.
  `paint-order:stroke fill` is the load-bearing part. The highlight colours moved with
  it and the separate mobile path collapsed into one rule
- Orphaned media pruned. `scripts/prune_bucket.py` walks the same references
  `verify_payload.py` checks, in the opposite direction. Removed 1,306 objects from the
  bucket and 1,381 files (45.7 MB) from the local staging mirror — pruning only the
  bucket would have been undone by the next upload from a dev machine
- Attribution on the site: home footer, drawer line, README
- Main unit stories ingested. Six arcs swept (252 probes); only Nightcord at 25:00 and
  Wonderlands×Showtime were ever retouched. Modelled as pseudo-events in id range
  9000+ so search, range filtering, the drawer and a future version browser need no
  second code path
- Event banner and unit icon in the drawer, grouped by unit and collapsible, with the
  event list cached per range so a route change no longer recreates 38 `<img>` elements
- Event title art in the page header, from the **EN** mirror rather than the indexer's
  JP `logo_url`; the magnitude chip came out of the header at the same time
- `verify_payload.py` now checks banners, event logos and unit logos, not just sprites and
  backgrounds — adding an asset class and never uploading it used to pass
- Change magnitude: breadth + depth per transition, badged as substantial rewrite /
  revised wording / punctuation only. Two axes, because *Wonder Magical Showtime!* touched
  167 lines and every one was adding a curly quote
- Empty state when the in-event filter matches nothing
- Renamed `master` → `main`; deploy triggers on `main`, Pages source repointed
- Language classifier fixed: counts letters, not characters — 2,629 → 957 real rewrites
- Fingerprint sweep to find changed bundles for ~1 byte each
- Per-transition payload and version-range UI
- Content-addressed sprites, served from a bucket with a one-year immutable cache
- Render on a free Windows CI runner (Mesa llvmpipe) — no VM
- Daily poll, incremental diff, loud failure
