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

## 2. Attribution disclaimer on the site

State plainly that all story text, character art and assets belong to Colorful Palette /
SEGA / Crypton, that this is an unofficial fan project, and that source data comes from
the game CDN and `sekai.best`.

**Why:** it is other people's copyrighted work, presented at length. It should say so
without needing to be asked.

**Watch out for:** it needs to be visible, not buried — the home hero footer and the
drawer are both reasonable. Also credit `Sekai-World/sekai-master-db-en-diff` for the
version index and `sekai.best` for the asset mirror, since the pipeline depends on both.

---

## 3. Style the dialogue like the game

Replace the 94%-opaque white card with the game's look. The viewer's assets specify it
exactly: `src/assets/live2d_player_ui/text_background.svg` is a **vertical black gradient at
0.2–0.3 opacity** spanning the bottom of the stage, and `layer/Dialog.ts` draws text
`#ffffff` with `stroke #4a496899` — white text with a soft dark outline.

**Watch out for:** the diff highlight colours go with it. `#a52f2f` / `#126b48` were picked
against white and will be unreadable on a dark panel; the mobile variants (`#ff9b9b` /
`#8ce0b6`) are the starting point, and the two code paths can then merge. A screenshot would
settle how much stage height the panel covers and where the name plate sits.

## 4. Prune orphaned sprites from the bucket

Every reclassification leaves sprites in `gs://sekai-story-diff-assets` that no payload
references. The bucket holds 2,390 sprites against 1,161 the payload references.

**Why it can wait:** they are immutable, content-addressed, and cost roughly $0.001/month.
Nothing breaks.

**Why it should not wait forever:** the set only grows, and there is currently no way to
tell a live sprite from a dead one without rebuilding the payload. A script that diffs the
bucket listing against `web/src/data.json` and deletes the difference is small — the pieces
already exist in `scripts/verify_payload.py`, which walks exactly the same references in the
opposite direction. Do it after the classifier fix lands, when the orphan set is at its largest and the
saving is easiest to confirm.

Banners are orphaned the same way and should go in the same sweep: 45 files under
`event/` for the 38 events the payload still references.

---

## Done

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
