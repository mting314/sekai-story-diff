# Backlog

Nothing open.

New entries say what the thing is, why it matters, and what makes it non-trivial — the
last part being the bit worth knowing before picking one up.

## Not doing

### Bilingual mode — Japanese alongside the English on the stage

Both plausible layouts were built and rejected on sight, so this is closed rather than
pending. Reopen only with a third shape, not with either of these.

*A row spanning the pair* was implemented and reverted. *A column inside each panel* —
Cleista's shape (`.reader.has-secondary .dialogue-overlay { grid-template-columns: 1fr
1fr }`) — was mocked at real widths with real frames and rejected too.

The width was the concrete problem. Their stage runs to 940px; a card in our grid is
~540px and ~366px on a phone, so a second column leaves the English at roughly 230px and
150px. The dialogue is `clamp(10.5px, 4.6cqmin, 17px)` and does not shrink to compensate,
so it wraps instead and pushes the overlay further up over the art it is sitting on. The
duplication is the other half: the Japanese is the same for both panels, so a column in
each shows it twice per frame.

The Japanese is still on every frame (`f.jp`, 100% coverage) in the figcaption, which is
where it stays.

## Done

- Lines edited at more than one release are flagged on the frame, linking to the other
  occurrence with an explicit range so it resolves from anywhere. All five in the corpus
  are reverts that end exactly where they started, and the note says so. Built as a flag
  rather than the obvious "net diff across releases" view, which would have rendered five
  empty results
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
