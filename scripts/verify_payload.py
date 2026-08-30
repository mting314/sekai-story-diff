"""Refuse to publish a payload the site cannot fully render.

The site hides a changed line until its scene exists, so a payload that references a
sprite which was never written does not look broken — it looks like a smaller diff.
That is the one failure mode of an unattended pipeline that nobody would notice, so it
is checked explicitly before anything is committed.

Checking the local ``web/public`` alone was not enough. Those directories are gitignored
— the media lives in the bucket — and the only thing that uploads them is the render job
in ``update.yml``. So a build run on a laptop leaves every new asset present locally,
passes, and publishes a payload pointing at objects the bucket has never held: the site
returns 200 with holes in it, which is precisely the invisible failure this script
exists to prevent. Bringing event 145 into the payload did exactly that with three
files.

So the question asked here is the one that matters — *will a browser be able to fetch
this?* — and it has three answers per asset:

    in the bucket            already published, nothing to do
    local only               will be published by the next rsync
    neither                  a hole; recoverable only if the mirror still has it

Backgrounds, banners and logos come off ``storage.sekai.best`` and are re-fetched here
when they are missing from both places. Sprites cannot be: they are Live2D renders that
only ``build_web_gallery.py`` can produce, so a missing one is always a hard failure.

    python scripts/verify_payload.py                     # must already be published
    python scripts/verify_payload.py --pending-upload-ok # CI: an rsync follows
    python scripts/verify_payload.py --no-bucket         # offline; local check only
"""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from build_web_gallery import (  # noqa: E402
    BANNER_WIDTH,
    BG_WIDTH,
    LOGO_HEIGHT,
    build_backgrounds,
    event_meta,
    fetch_banner,
    fetch_logo,
)

# Matches VITE_ASSET_BASE in .github/workflows/deploy.yml — the base the built site
# actually requests from, so probing it tests what a visitor gets rather than what we
# believe we uploaded.
ASSET_BASE = "https://storage.googleapis.com/sekai-story-diff-assets/"

_session = requests.Session()
_session.headers["User-Agent"] = "sekai-story-diff"


def published(paths: set[str], base: str, workers: int) -> set[str]:
    """Which of these object paths the bucket actually serves.

    One HEAD each rather than a single bucket listing: the bucket allows anonymous
    reads but not anonymous ``storage.objects.list``, so listing needs credentials that
    a contributor may not have, while a HEAD needs none and tests the exact URL the
    page will request.
    """
    def probe(path: str) -> tuple[str, bool]:
        for attempt in range(3):
            try:
                resp = _session.head(base + path, timeout=30)
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    return path, False
                continue
            if resp.status_code == 200:
                return path, True
            if resp.status_code == 404:
                return path, False
        return path, False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return {p for p, ok in pool.map(probe, sorted(paths)) if ok}


def referenced_assets(payload: dict) -> tuple[set[str], list[str]]:
    """Every object path the site will request, plus structural complaints."""
    problems: list[str] = []
    sprites = payload.get("sprites", {})
    frames = [
        frame
        for event in payload.get("events", [])
        for transition in event.get("transitions", [])
        for episode in transition.get("episodes", [])
        for frame in episode.get("frames", [])
    ]

    keys = {layer["key"] for frame in frames for layer in frame.get("layers", [])}
    problems += [
        f"frame references sprite key {k}, which has no entry"
        for k in sorted(keys - set(sprites))[:10]
    ]

    paths: set[str] = set()
    for key in sorted(keys & set(sprites)):
        name = sprites[key].get("file")
        if not name:
            problems.append(f"sprite {key} has no filename recorded")
        else:
            paths.add(f"sprites/{name}")

    paths |= {
        f"bg/{frame['bg']}.webp"
        for frame in frames
        if frame.get("bg") and not frame.get("cover")
    }
    # Event art was not checked at all once, which is how a whole asset class could be
    # added to the payload and never uploaded: the site still returns 200, just with
    # holes in it.
    paths |= {
        path
        for event in payload.get("events", []) + payload.get("pending", [])
        for key in ("banner", "logo", "unitLogo")
        if (path := event.get(key))
    }
    return paths, problems


def refetch(payload: dict, assets: Path, gaps: set[str], quality: int) -> set[str]:
    """Pull back what the mirror can still supply. Returns the paths now on disk.

    Reuses the builder's own fetchers rather than reimplementing them: the banner is
    flattened to RGB and the logo is not, because flattening a transparent logo leaves
    a black slab behind the lettering, and that distinction is not worth having in two
    places.
    """
    recovered: set[str] = set()

    backgrounds = {p.removeprefix("bg/").removesuffix(".webp") for p in gaps if p.startswith("bg/")}
    if backgrounds:
        print(f"  fetching {len(backgrounds)} background(s) from the mirror…")
        build_backgrounds(backgrounds, assets / "bg", BG_WIDTH, quality)
        recovered |= {f"bg/{n}.webp" for n in backgrounds if (assets / "bg" / f"{n}.webp").exists()}

    meta = event_meta()
    for event in payload.get("events", []) + payload.get("pending", []):
        info = meta.get(event.get("id"), {})
        banner, logo = event.get("banner"), event.get("logo")
        if banner in gaps:
            print(f"  fetching banner for {event.get('name')}…")
            if fetch_banner(info.get("banner", ""), assets / banner, BANNER_WIDTH, quality):
                recovered.add(banner)
        if logo in gaps:
            print(f"  fetching logo for {event.get('name')}…")
            if fetch_logo(event.get("bundleName", ""), info.get("logo", ""),
                          assets / logo, quality):
                recovered.add(logo)
    return recovered


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="web/src/data.json")
    ap.add_argument("--assets", default="web/public")
    ap.add_argument("--base", default=ASSET_BASE, help="public asset base the site requests")
    ap.add_argument("--no-bucket", action="store_true",
                    help="skip the bucket probe; check the local tree only")
    ap.add_argument("--pending-upload-ok", action="store_true",
                    help="accept assets that exist locally but are not published yet. For "
                         "the render job, which verifies before it rsyncs — everything it "
                         "just drew is local-only by definition")
    ap.add_argument("--no-fetch", action="store_true",
                    help="report assets missing everywhere instead of re-fetching them")
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    data_path, assets = Path(args.data), Path(args.assets)
    if not data_path.exists():
        raise SystemExit(f"{data_path} is missing — the build did not produce a payload")
    payload = json.loads(data_path.read_text())

    paths, problems = referenced_assets(payload)
    on_disk = {p for p in paths if (assets / p).exists()}

    frames = sum(
        len(episode["frames"])
        for event in payload.get("events", [])
        for transition in event["transitions"]
        for episode in transition["episodes"]
    )
    print(f"{len(payload.get('events', []))} events, {frames} frames")
    print(f"  assets referenced: {len(paths)}  present locally: {len(on_disk)}")

    if args.no_bucket:
        problems += [f"{p} is referenced but absent locally" for p in sorted(paths - on_disk)[:10]]
        finish(problems, "every referenced asset is present locally (bucket not checked)")
        return

    print(f"  probing {args.base}…")
    live = published(paths, args.base, args.workers)
    gaps = paths - live - on_disk
    print(f"  already published: {len(live)}")

    if gaps and not args.no_fetch:
        recovered = refetch(payload, assets, gaps, args.quality)
        on_disk |= recovered
        gaps -= recovered
        if recovered:
            print(f"  recovered {len(recovered)} from the mirror; they still need uploading")

    # Nowhere to be found. A sprite is ours and can only be redrawn; the rest means the
    # mirror no longer serves it, which is a genuine dead end worth saying out loud.
    for path in sorted(gaps)[:10]:
        how = ("re-run build_web_gallery.py to redraw it" if path.startswith("sprites/")
               else "the mirror no longer serves it")
        problems.append(f"{path} is in neither the bucket nor {assets} — {how}")

    unpublished = sorted((paths - live) - gaps)
    if unpublished and not args.pending_upload_ok:
        problems.append(
            f"{len(unpublished)} asset(s) exist locally but are not in the bucket, so the "
            f"published site would 404 them. Upload before committing the payload:"
        )
        problems += [f"    {p}" for p in unpublished[:10]]
        problems.append(
            f"    gcloud storage rsync {assets} gs://sekai-story-diff-assets --recursive"
        )
    elif unpublished:
        print(f"  {len(unpublished)} local-only, pending the upload that follows")

    finish(problems, "every referenced asset is published — safe to publish")


def finish(problems: list[str], good: str) -> None:
    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for line in problems[:24]:
            print(f"  {line}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  {good}")


if __name__ == "__main__":
    main()
