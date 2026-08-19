# Backlog

Ordered roughly by how much they unblock or how visible they are. Each entry says what
it is, why it matters, and what makes it non-trivial — the last part is the bit worth
knowing before picking one up.

---

## 1. Rename `master` → `main`

Rename the default branch, repoint the deploy and update workflows, and delete `master`.

**Why:** `main` is the convention everywhere else in this workspace, and the workflows
currently hardcode `master`.

**Watch out for:**
- `.github/workflows/deploy.yml` and `update.yml` both trigger on `branches: [main, master]`
  / `master`; the update workflow also pushes, so it needs the new name.
- The GitHub Pages source is pinned to a branch in repo settings — renaming without
  updating it silently stops deploys.
- `feat/live2d-frame-set` is fully merged and can be deleted at the same time.

---

## 2. Event banner and unit icon in the sidebar

The drawer lists events as plain text. The home cards already show banner art, a unit
logo and the unit colour; the sidebar should too.

**Why:** the drawer is the main way to move between events once you are reading one, and
45 text rows are hard to scan.

**Watch out for:** the drawer is rebuilt on every route change, so 45 banner images want
`loading="lazy"` or a small thumbnail variant — the banners are 640px wide and sized for
cards, not 40px rows. Data is already in the payload (`banner`, `unitLogo`, `colour`).

---

## 3. Version browser

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

## 4. Classify each change: substantial rewrite vs typo fix

At a glance, was this event's diff a real retranslation or a handful of comma fixes?

**Why:** *First Star After the Rain* rewrote 359 lines; *Screaming?!* changed two
characters of a homoglyph. Both currently look like "an event that changed".

**Watch out for:** the signal is already half-computed. `LineChange.ratio` is a
`SequenceMatcher` score on the normalised text, and `kind` separates `text` /
`linebreak` / `speaker`. A first cut could bucket on median ratio plus changed-line
share — high ratio and few lines means punctuation and grammar; low ratio across many
lines means a rewrite. Worth sanity-checking against known cases: *Screaming?!* is a
pure homoglyph swap, *Happy Lovely Everyday!* is mostly quotation marks, *Curtain Call*
has a genuine rewording. Do the classification in the pipeline and store it, so the
threshold can move without re-diffing.

---

## 5. Attribution disclaimer on the site

State plainly that all story text, character art and assets belong to Colorful Palette /
SEGA / Crypton, that this is an unofficial fan project, and that source data comes from
the game CDN and `sekai.best`.

**Why:** it is other people's copyrighted work, presented at length. It should say so
without needing to be asked.

**Watch out for:** it needs to be visible, not buried — the home hero footer and the
drawer are both reasonable. Also credit `Sekai-World/sekai-master-db-en-diff` for the
version index and `sekai.best` for the asset mirror, since the pipeline depends on both.

---

## Done

- Fingerprint sweep to find changed bundles for ~1 byte each
- Per-transition payload and version-range UI
- Content-addressed sprites, served from a bucket with a one-year immutable cache
- Render on a free Windows CI runner (Mesa llvmpipe) — no VM
- Daily poll, incremental diff, loud failure
