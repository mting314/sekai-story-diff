"""Find which story bundles changed between which asset versions, for ~1 byte each.

Diffing a version pair means downloading and decrypting both sides, which is far too
expensive to do speculatively across every pair. But the CDN hands out a fingerprint for
almost nothing: a ranged ``GET`` of one byte returns the object's ``ETag`` (an MD5 of the
whole object), so a bundle can be identified at a version without fetching it.

    event_story/event_stella_2020/scenario
      5.4.0.20  50719afd18f39f24982d2576c5ac898e
      5.4.0.30  ba2b6d1b4a386007d916c6533d9f47e5   <- changed

Use a ranged GET, not HEAD: a proxy in front of this CDN swallows the headers on HEAD.

An ETag change is *necessary but not sufficient* for a text change — a bundle can be
repacked, or change in another locale, without the English text moving. Curtain Call's
bytes changed at 5.4.0.40 -> 5.5.0.1 while its text only moved at 5.5.0.20 -> 5.5.1.0. So
this produces *candidates*; scripts/diff_transitions.py confirms them by diffing.

Every cell is immutable — a given (version, bundle) can never change — so the cache is
only ever appended to and a re-run costs nothing.

    python scripts/fingerprint_bundles.py            # incremental sweep
    python scripts/fingerprint_bundles.py --probe    # just find the live version window
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from build_version_index import load as load_versions

MASTER = Path("data/master")
FINGERPRINTS = Path("data/fingerprints.json")
TRANSITIONS = Path("data/transitions.json")
# a bundle that has existed for the whole retention window, used to decide which versions
# the CDN still serves before sweeping everything against them
REFERENCE_BUNDLE = "event_story/event_stella_2020/scenario"

_session = requests.Session()
_session.headers.update(
    {
        "Accept": "application/octet-stream",
        "User-Agent": "UnityPlayer/2022.3.52f1",
        "X-Platform": "Android",
        "X-Unity-Version": "2022.3.52f1",
        "X-App-Version": "5.5.0",
        "X-App-Hash": "d6f805a4-3d77-4967-91b8-a045d97e756c",
        "X-DeviceModel": "sssekai",
        "X-OperatingSystem": "Android",
        "Range": "bytes=0-0",
    }
)

MISSING = "__404__"


APP_VERSION = "5.5.0"
APP_HASH = "d6f805a4-3d77-4967-91b8-a045d97e756c"


def base_url() -> str:
    """Resolve the assetbundle host, reusing fetch_official_bundles' handshake."""
    from fetch_official_bundles import asset_host_hash

    profile, host_hash = asset_host_hash(APP_VERSION, APP_HASH)
    return f"https://n-{profile}-{host_hash}-assetbundle.sekai-en.com"


def fingerprint(base: str, version: str, digest: str, bundle: str) -> str:
    """ETag of the bundle at that version, or MISSING. One byte of payload."""
    url = f"{base}/{version}/{digest}/android/{bundle}"
    for attempt in range(3):
        try:
            resp = _session.get(url, timeout=45)
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return MISSING
            time.sleep(2)
            continue
        if resp.status_code in (200, 206):
            return resp.headers.get("etag", "").strip('"') or MISSING
        if resp.status_code == 404:
            return MISSING
        if attempt == 2:
            return MISSING
        time.sleep(2)
    return MISSING


def event_bundles() -> list[str]:
    stories = json.loads((MASTER / "eventStories.json").read_text())
    seen, out = set(), []
    for story in stories:
        bundle = f"event_story/{story['assetbundleName']}/scenario"
        if bundle not in seen:
            seen.add(bundle)
            out.append(bundle)
    return out


def live_versions(base: str, versions: list[dict], workers: int) -> list[dict]:
    """Versions the CDN still serves, found by probing one long-lived bundle."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        marks = list(
            pool.map(lambda v: fingerprint(base, v["version"], v["hash"], REFERENCE_BUNDLE), versions)
        )
    live = [v for v, mark in zip(versions, marks) if mark != MISSING]
    return live


def transitions_from(cells: dict[str, str], order: list[str]) -> list[dict]:
    """Adjacent version pairs where the fingerprint moved between two present versions.

    A bundle appearing for the first time is the event not existing yet, not a change, so
    pairs that touch a missing side are never emitted.
    """
    out = []
    previous: tuple[str, str] | None = None
    for version in order:
        mark = cells.get(version)
        if mark is None or mark == MISSING:
            continue
        if previous and previous[1] != mark:
            out.append({"new": version, "old": previous[0]})
        previous = (version, mark)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--probe", action="store_true", help="only report the live version window")
    ap.add_argument("--limit-bundles", type=int, default=0, help="sweep only the first N (debug)")
    args = ap.parse_args()

    versions = load_versions()
    base = base_url()
    print(f"{len(versions)} versions in the index; probing which the CDN still serves…")
    live = live_versions(base, versions, args.workers)
    if not live:
        raise SystemExit("no versions responded — the host handshake or headers are wrong")
    print(f"  {len(live)} live: {live[0]['date']} ({live[0]['version']}) .. "
          f"{live[-1]['date']} ({live[-1]['version']})")
    dead = len(versions) - len(live)
    print(f"  {dead} older versions have been purged from the CDN and are unreachable")
    if args.probe:
        return

    bundles = event_bundles()
    if args.limit_bundles:
        bundles = bundles[: args.limit_bundles]
    cache = json.loads(FINGERPRINTS.read_text()) if FINGERPRINTS.exists() else {}

    todo = [
        (bundle, v)
        for bundle in bundles
        for v in live
        if v["version"] not in cache.get(bundle, {})
    ]
    print(f"{len(bundles)} bundles x {len(live)} versions = {len(bundles) * len(live)} cells; "
          f"{len(todo)} to fetch ({len(todo)} bytes of payload)")

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        marks = pool.map(lambda job: fingerprint(base, job[1]["version"], job[1]["hash"], job[0]), todo)
        for (bundle, v), mark in zip(todo, marks):
            cache.setdefault(bundle, {})[v["version"]] = mark
            done += 1
            if done % 500 == 0:
                print(f"  {done}/{len(todo)}")
                FINGERPRINTS.write_text(json.dumps(cache, indent=0))
    FINGERPRINTS.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINTS.write_text(json.dumps(cache, indent=0))

    order = [v["version"] for v in live]
    found = {b: t for b in bundles if (t := transitions_from(cache.get(b, {}), order))}
    TRANSITIONS.write_text(
        json.dumps({"bundles": found, "versions": live}, indent=1), encoding="utf-8"
    )

    total = sum(len(t) for t in found.values())
    present = sum(1 for b in bundles if any(m != MISSING for m in cache.get(b, {}).values()))
    print(f"\nwrote {FINGERPRINTS} and {TRANSITIONS}")
    print(f"  {present}/{len(bundles)} bundles exist in the live window")
    print(f"  {len(found)} bundles changed at least once; {total} candidate transitions")
    print(f"\n  candidates still need confirming — an ETag move is not always a text move.")
    print(f"  next: scripts/diff_transitions.py  (fetches + diffs each candidate)")
    for bundle, trans in sorted(found.items(), key=lambda kv: -len(kv[1]))[:10]:
        pairs = ", ".join(f"{t['old']}->{t['new']}" for t in trans[:3])
        more = f" (+{len(trans) - 3})" if len(trans) > 3 else ""
        print(f"    {len(trans):2d}  {bundle.split('/')[1]:28s} {pairs}{more}")


if __name__ == "__main__":
    main()
