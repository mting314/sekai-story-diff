# sekai-story-diff

Tracks **what Project Sekai changes in its localised story text between releases**, using
official data on both sides.

The public mirror (`storage.sekai.best`) only ever serves the *current* text. The game's
own CDN is addressed by asset version and keeps old versions for roughly ten months, so
pinning two versions gives an exact official-vs-official diff:

```
https://n-{profile}-{abHostHash}-assetbundle.sekai-en.com/{assetVersion}/{assetHash}/{platform}/{bundle}
```

`assetVersion` + `assetHash` for every EN release come from the git history of
`versions.json` in [`Sekai-World/sekai-master-db-en-diff`][endiff]; `profile` and
`abHostHash` come from `game-version.sekai-en.com/{appVersion}/{appHash}` (AES-encrypted
msgpack). Bundles are decrypted with [`sssekai`][sssekai] and read with UnityPy.

[endiff]: https://github.com/Sekai-World/sekai-master-db-en-diff
[sssekai]: https://github.com/mos9527/sssekai

### What is covered

Every EN **event story** in the live window, plus the six **main unit arcs**. Unit arcs are
one bundle per chapter, carried through the pipeline as pseudo-events in id range 9000+ so
that search, version-range filtering, the drawer and the release view need no second code
path — event ids run to 178, chapter ids to 6, so the ranges cannot collide.

Sweeping the arcs cost 6 × 42 = 252 probes and found that only two were ever retouched:
Nightcord at 25:00 (4.1.50.20, mostly wording) and Wonderlands×Showtime (5.1.0.1, almost
entirely adding quotation marks around in-story dialogue). Leo/need, MORE MORE JUMP!,
Vivid BAD SQUAD and Piapro have never been revised.

### How far back this can go

Not to launch, and never will. The version index knows **194 EN releases back to
2021-12-13**, but probing every one of them against the CDN finds only **42 still served**
— from **2025-09-26 (4.0.0.1)** onward. The boundary is clean: the newest dead version is
3.8.51.20, four days before the oldest live one. It is a rolling ~11-month retention
window, not scattered gaps.

The pre-2025-09 text is simply gone. `storage.sekai.best` mirrors only the current version
of each asset, and `sekai-master-db-en-diff` has deep history but holds master-DB JSON —
story dialogue lives in the scenario asset bundles, not the master DB.

Two consequences. The floor **rises**: every release ages out after ~11 months, so a
transition not diffed while it is live is lost for good — which is the real reason the
daily job matters. And the window is currently **fully covered**: all 42 live versions are
fingerprinted, and of the 41 adjacent pairs, 22 rendered a diff, 16 had no bundle re-hash
at all, and 3 re-hashed without the English text moving (confirmed by fetching both sides).

## First result

The EN release that rewrote **Event 1 · First Star After the Rain**:

| | |
|---|---|
| Asset version | `5.4.0.20` (2026-06-30) → `5.4.0.30` (2026-07-03) |
| Events touched | 1 (all 8 episodes) |
| Changed lines | 405 of 572 — 357 rewordings, 46 line-wrap-only, 2 name-plate |

Line counts match index-for-index on both sides: every line was re-edited in place,
nothing added or cut.

## Pipeline

```bash
uv sync --group render     # everything; omit --group render for the diff half only

# 1. index every release, then find which bundles changed between which of them
uv run python scripts/build_version_index.py      # data/versions_en.json  (193 releases + hashes)
uv run python scripts/fingerprint_bundles.py      # data/transitions.json  (candidates)

# 2. confirm each candidate by actually fetching and diffing it
uv run python scripts/diff_transitions.py         # data/transitions/*.json

# 3. the site
uv run python scripts/build_web_gallery.py --changes 'data/official_changes*.json' 'data/transitions/*.json'
cd web && bun install && bun run build     # -> web/dist

# reports and the baked gallery, from a single pair
uv run python scripts/report.py                   # data/REPORT.md + data/changed_lines.csv
uv run python scripts/render_live2d_frames.py     # 1 frame per changed line, posed Live2D scenes
uv run python scripts/build_gallery.py --images data/images_live2d
```

## Finding the diffs

The mirror records one `Last-Modified` per asset, so it can only ever reveal an event's
*most recent* change. The version-addressed game CDN can do better, and cheaply: a ranged
`GET` of one byte returns the object's `ETag`, so a bundle can be fingerprinted at a
release without downloading it.

```
event_story/event_stella_2020/scenario
  5.4.0.20  50719afd18f39f24982d2576c5ac898e
  5.4.0.30  ba2b6d1b4a386007d916c6533d9f47e5   <- changed
```

Use a ranged GET, not `HEAD` — a proxy in front of the CDN swallows the headers on HEAD.
Sweeping 211 event bundles across the 41 releases still served costs 8,651 requests and
8.6 KB, and every cell is immutable, so the cache is only ever appended to.

An ETag move is **necessary but not sufficient**: a bundle can be repacked without the
English text changing. `diff_transitions.py` confirms each candidate by fetching and
diffing it, and drops the rest.

## What "changed" means

Only about a fifth of the changed lines in the catalogue are editorial rewrites:

| | |
|---|---|
| JP → EN | 9,620 — Japanese placeholder text replaced by its first English localisation |
| EN → JP | 1,074 — the reverse leg of that round trip |
| **English rewrite** | **2,779** |

An EN story asset does not always contain English. `textutil.language_shift` classifies
every line and the class is stored in the diff, so the site excludes the language flips
by default (`--langs`) without that decision being baked into the data.

`scripts/probe_asset_mtimes.py` still sweeps `Last-Modified` on the mirror, but the
fingerprint sweep supersedes it for finding work: it sees every change in the retention
window rather than only the latest one per asset.

## Local Live2D rendering (no browser)

`scripts/live2d_scene.py` rebuilds the actual staged scene for a line — the background
live at that point, every character on stage, in their costume, with the body motion and
facial expression the scenario specifies. It runs fully offline:

* offscreen **legacy CGL context** (GL 2.1 / GLSL 1.20 — Cubism's GL renderer ships
  `#version 120` shaders, so a core 3.3 context silently renders nothing)
* **Cubism Core 5.1** native through `live2d-py`
* models from the official CDN via `sssekai live2dextract`; motions and expressions from
  `sekai-live2d-assets/live2d/motion/<dir>/<base>_motion_base/{motion,facial}/`

Transform constants mirror sekai-viewer's player (`Live2D.ts`): scale =
`stage_height / model.originalHeight * 2.1` (`1.8` in three-model layout), anchor `0.5`,
`y = stage_height * (position.y + 0.3)`, and the side→x table from
`action/character_layout.ts`.

Scene state is walked out of `SpecialEffectData` alongside the talks, so a frame gets
the background, flashback dim (flat black at `0.3`, as `flashback_filter` does) and
live2d ambient grade (`AmbientColor*`) that are actually in force at that line. Effects
the game hides as the next talk opens — Telop, PlaceInfo, shakes — are deliberately not
tracked. Three findings from calibrating against the game:

* **Pose time.** Sampling each motion at its final frame is right, not a guess: all 454
  motions used in event 1 are flat from 85 % of their duration at the latest (median
  64 %), so the last frame *is* the held pose the line is read against.
* **`isEnabledFlipDisplay`** is not a story-scene mirror flag. Applying it reverses the
  lettering on Shiho's hoodie and Ichika's jacket, which the game never shows. The
  mechanism is implemented behind `--flip`, and left off.
* **`DepthType`** is `Top` for all 778 `LayoutData` rows in event 1, so the back-row
  ladder (`--depth-step`, draw order + scale) never fires here and is unverified
  against the game. sekai-viewer ignores the field outright.

## Layout

```
scripts/   pipeline (fetch → diff → report → render)
data/      caches + outputs (gitignored; ~700 MB)
  official/{version}/   decrypted scenario data per pinned asset version
  official_changes.json, REPORT.md, changed_lines.csv
  images/, images_live2d/
```

## Related

* `sekai-viewer` fork, branch `feat/story-version-diff` — the same diff as a browsing
  experience, reusing the viewer's faithful Live2D story player.
