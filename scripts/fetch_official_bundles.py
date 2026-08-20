"""Download + decrypt official EN story bundles at a pinned asset version.

The live mirror (``storage.sekai.best``) only ever serves the current text, but the
game's own CDN is addressed by asset version:

    https://n-{profile}-{abHostHash}-assetbundle.sekai-en.com/{assetVersion}/{assetHash}/{platform}/{bundle}

and old versions stay served for months. ``versions.json`` in ``sekai-master-db-en-diff``
carries the (assetVersion, assetHash) pair for every EN release, so pinning a version
gives us the *official* text as it shipped that day — the only sound baseline for an
official-vs-official diff.

Needs ``sssekai`` + ``UnityPy`` (bundle decrypt + typetree read).
"""

from __future__ import annotations

import argparse
import json
import warnings
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests

try:
    from sssekai.crypto.APIManager import SEKAI_APIMANAGER_KEYSETS, decrypt
    from sssekai.unity.AssetBundle import load_assetbundle
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "needs sssekai + UnityPy — run with an interpreter that has them, e.g.\n"
        "  ~/github/sekai-reverse-engineering/.venv/bin/python "
        "scripts/data/fetch_official_bundles.py ..."
    ) from exc

warnings.filterwarnings("ignore")

GAME_VERSION_EN = "https://game-version.sekai-en.com"
MASTER = Path("data/master")
OUT = Path("data/official")

_session = requests.Session()


def _headers(app_version: str, app_hash: str) -> dict[str, str]:
    return {
        "Accept": "application/octet-stream",
        "Content-Type": "application/octet-stream",
        "User-Agent": "UnityPlayer/2022.3.52f1",
        "X-Platform": "Android",
        "X-DeviceModel": "sssekai",
        "X-OperatingSystem": "Android",
        "X-Unity-Version": "2022.3.52f1",
        "X-App-Version": app_version,
        "X-App-Hash": app_hash,
    }


def asset_host_hash(app_version: str, app_hash: str) -> tuple[str, str]:
    """``game-version`` → (profile, assetbundleHostHash); msgpack under AES."""
    import msgpack

    resp = _session.get(f"{GAME_VERSION_EN}/{app_version}/{app_hash}", timeout=45)
    resp.raise_for_status()
    data = msgpack.unpackb(
        decrypt(resp.content, SEKAI_APIMANAGER_KEYSETS["en"]), strict_map_key=False
    )
    return data["profile"], data["assetbundleHostHash"]


def scenarios_from_bundle(blob: bytes) -> dict[str, dict]:
    """Decrypt a scenario bundle → ``{scenario name: ScenarioData typetree}``."""
    env = load_assetbundle(BytesIO(blob))
    out: dict[str, dict] = {}
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        try:
            tree = obj.read_typetree()
        except Exception:  # noqa: BLE001 - non-scenario MonoBehaviours
            continue
        if "TalkData" in tree and tree.get("m_Name"):
            out[tree["m_Name"]] = tree
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True, help="assetVersion, e.g. 5.4.0.30")
    ap.add_argument(
        "--hash",
        default="",
        help="assetHash; looked up in data/versions_en.json when omitted",
    )
    ap.add_argument("--app-version", default="5.5.0")
    ap.add_argument("--app-hash", default="d6f805a4-3d77-4967-91b8-a045d97e756c")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--kind",
        default="event",
        choices=["event", "unit"],
        help="which story bundles to pull",
    )
    ap.add_argument(
        "--bundles",
        nargs="*",
        default=[],
        help="only these bundles, e.g. event_story/event_stella_2020/scenario",
    )
    ap.add_argument("--events", nargs="*", type=int, default=[], help="only these event ids")
    args = ap.parse_args()

    # Pulling one bundle used to mean running from a scratch cwd with a hand-trimmed
    # eventStories.json, because the only selection was "all of them".
    if not args.hash:
        from build_version_index import resolve

        args.hash = resolve(args.version)
        print(f"resolved {args.version} -> {args.hash}")

    _session.headers.update(_headers(args.app_version, args.app_hash))
    profile, host_hash = asset_host_hash(args.app_version, args.app_hash)
    base = f"https://n-{profile}-{host_hash}-assetbundle.sekai-en.com"
    print(f"asset CDN {base} @ {args.version}")

    if args.kind == "event":
        stories = json.loads((MASTER / "eventStories.json").read_text())
        bundles = [
            (s["eventId"], f"event_story/{s['assetbundleName']}/scenario") for s in stories
        ]
    else:
        # Chapters key on "id"; there is no "seq" field, which this branch assumed until
        # it was first actually run. One bundle holds a whole chapter's episodes, the
        # same shape as an event's scenario bundle.
        chapters = json.loads((MASTER / "unitStories.json").read_text())
        bundles = [
            (ch["id"], f"scenario/unitstory/{ch['assetbundleName']}")
            for unit in chapters
            for ch in unit.get("chapters", [])
        ]

    if args.bundles:
        keep = set(args.bundles)
        bundles = [b for b in bundles if b[1] in keep]
    if args.events:
        keep_ids = set(args.events)
        bundles = [b for b in bundles if b[0] in keep_ids]
    if (args.bundles or args.events) and not bundles:
        raise SystemExit("no bundles matched --bundles/--events")
    print(f"{len(bundles)} bundle(s) to consider")

    out_root = Path(args.out) / args.version
    out_root.mkdir(parents=True, exist_ok=True)

    def work(item: tuple[int, str]) -> str:
        _, bundle = item
        dest = out_root / (bundle.replace("/", "__") + ".json")
        if dest.exists():
            return "cached"
        url = f"{base}/{args.version}/{args.hash}/android/{bundle}"
        try:
            resp = _session.get(url, timeout=90)
        except Exception:  # noqa: BLE001
            return "error"
        if resp.status_code != 200:
            return f"http{resp.status_code}"
        try:
            scenarios = scenarios_from_bundle(resp.content)
        except Exception:  # noqa: BLE001
            return "decrypt-error"
        dest.write_text(
            json.dumps({"bundle": bundle, "scenarios": scenarios}, ensure_ascii=False),
            encoding="utf-8",
        )
        return "fetched"

    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, status in enumerate(pool.map(work, bundles), 1):
            counts[status] = counts.get(status, 0) + 1
            if i % 40 == 0:
                print(f"  {i}/{len(bundles)} {counts}")
    print("done:", counts)


if __name__ == "__main__":
    main()
