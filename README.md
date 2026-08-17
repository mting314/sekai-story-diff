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
# interpreter with sssekai + UnityPy (bundle decrypt)
RE=~/github/sekai-reverse-engineering/.venv/bin/python

# 1. pull both versions of every event-story bundle
$RE scripts/fetch_official_bundles.py --version 5.4.0.20 --hash a1c93735-6fa9-4d32-ab91-f7f3dcf9470b
$RE scripts/fetch_official_bundles.py --version 5.4.0.30 --hash e41ccee9-d24f-4afe-9183-86640e8ee0ac

# 2. diff them line by line, then report
python scripts/diff_versions.py --old 5.4.0.20 --new 5.4.0.30
python scripts/report.py                 # data/REPORT.md + data/changed_lines.csv

# 3. images
python scripts/render_frames.py          # 1 frame per changed line (background + portrait)
python scripts/build_gallery.py          # data/images/gallery.html
python scripts/render_live2d_prototype.py  # real posed Live2D scenes (prototype)
```

`scripts/probe_asset_mtimes.py` sweeps `Last-Modified` on the mirror to find *which*
releases are worth diffing — events 24, 31, 74, 75, 111 and 155 were each re-uploaded on
their own dates and have not been diffed yet.

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
