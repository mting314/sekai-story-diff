# Backlog

Ordered roughly by how much they unblock or how visible they are. Each entry says what
it is, why it matters, and what makes it non-trivial — the last part is the bit worth
knowing before picking one up.

---

## 1. Version browser

A view over releases rather than events: for each asset version, which stories changed
and how many lines in each.

**Why:** the site answers "what changed in this event". The other natural question is
"what did this release change", and the data already supports it — `transitions.json`
plus the per-transition payloads are keyed exactly that way.

**Watch out for:** the payload is currently nested event → transition → episode → frame.
A release-first view needs the inverse index. Build it in `build_web_gallery.py` rather
than pivoting 2,629 frames in the browser on every render. Note 18 of 41 releases changed
nothing, so the list should probably show only those that did, with a count of the rest.

---

## Done

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
