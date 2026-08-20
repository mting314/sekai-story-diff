"""Refuse to publish a payload the site cannot fully render.

The site hides a changed line until its scene exists, so a payload that references a
sprite which was never written does not look broken — it looks like a smaller diff.
That is the one failure mode of an unattended pipeline that nobody would notice, so it
is checked explicitly before anything is committed.

    python scripts/verify_payload.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="web/src/data.json")
    ap.add_argument("--assets", default="web/public")
    args = ap.parse_args()

    data_path, assets = Path(args.data), Path(args.assets)
    if not data_path.exists():
        raise SystemExit(f"{data_path} is missing — the build did not produce a payload")
    payload = json.loads(data_path.read_text())
    problems: list[str] = []

    sprites = payload.get("sprites", {})
    referenced = {
        layer["key"]
        for event in payload.get("events", [])
        for transition in event.get("transitions", [])
        for episode in transition.get("episodes", [])
        for frame in episode.get("frames", [])
        for layer in frame.get("layers", [])
    }
    missing_entry = sorted(referenced - set(sprites))
    problems += [f"frame references sprite key {k}, which has no entry" for k in missing_entry[:10]]

    missing_file = []
    for key in sorted(referenced & set(sprites)):
        name = sprites[key].get("file")
        if not name:
            problems.append(f"sprite {key} has no filename recorded")
        elif not (assets / "sprites" / name).exists():
            missing_file.append(name)
    problems += [f"sprite file {n} is referenced but absent" for n in missing_file[:10]]

    backgrounds = {
        frame["bg"]
        for event in payload.get("events", [])
        for transition in event.get("transitions", [])
        for episode in transition.get("episodes", [])
        for frame in episode.get("frames", [])
        if frame.get("bg") and not frame.get("cover")
    }
    missing_bg = sorted(b for b in backgrounds if not (assets / "bg" / f"{b}.webp").exists())
    problems += [f"background {b} is referenced but absent" for b in missing_bg[:10]]

    # Event art was not checked here, which is how a whole asset class could be added to
    # the payload and never uploaded: the site still returns 200, just with holes in it.
    art = {
        path
        for event in payload.get("events", []) + payload.get("pending", [])
        for key in ("banner", "logo", "unitLogo")
        if (path := event.get(key))
    }
    missing_art = sorted(p for p in art if not (assets / p).exists())
    problems += [f"event art {p} is referenced but absent" for p in missing_art[:10]]

    frames = sum(
        len(episode["frames"])
        for event in payload.get("events", [])
        for transition in event["transitions"]
        for episode in transition["episodes"]
    )
    print(f"{len(payload.get('events', []))} events, {frames} frames")
    print(f"  sprite keys referenced: {len(referenced)}  entries: {len(sprites)}")
    print(f"  backgrounds referenced: {len(backgrounds)}")
    print(f"  event art referenced:   {len(art)}")

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for line in problems[:20]:
            print(f"  {line}", file=sys.stderr)
        raise SystemExit(1)
    print("  every referenced asset is present — safe to publish")


if __name__ == "__main__":
    main()
