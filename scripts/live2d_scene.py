"""Prototype: rebuild the actual in-scene Live2D frame for a story line.

Everything runs locally — no browser. A legacy CGL context (GL 2.1 / GLSL 1.20, which
is what the Cubism GL renderer's shaders target) is created offscreen, `live2d-py`
drives Cubism Core natively, and each character is drawn to an FBO with alpha and
composited over the scene background with Pillow.

Per line, the scenario data tells us exactly what the game shows:
  * which characters are on stage, where (``LayoutData`` side slots) and in what costume
  * the body motion + facial expression active for each of them
so the pose is reconstructed rather than approximated.

Model bundles come from the official CDN (decrypted with sssekai); motions and
expressions come pre-extracted off the mirror at
``sekai-live2d-assets/live2d/motion/<dir>/<base>_motion_base/{motion,facial}/``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import json
import subprocess
import time
from ctypes import byref, c_int, c_void_p
from pathlib import Path

import requests
from PIL import Image

LIVE2D_CDN = "https://storage.sekai.best/sekai-live2d-assets/live2d"
CACHE = Path("data/live2d")
SSSEKAI_PY = Path.home() / "github/sekai-reverse-engineering/.venv/bin/sssekai"

# Stage transform, copied from how the game's own renderer is reproduced in
# sekai-viewer (`Live2DPlayer/layer/Live2D.ts` + `action/character_layout.ts`) —
# these are the game's numbers, not eyeballed framing:
#   scale = stage_height / model.originalHeight * 2.1   (1.8 in three-model layout)
#   anchor = centre, x = stage_w * pos.x, y = stage_h * (pos.y + 0.3)
# CharacterLayoutPosition → (x, y) as fractions of the stage, per layout mode.
POSITION_MAPS = {
    "normal": {
        0: (0.5, 0.5), 4: (0.5, 0.5), 3: (0.3, 0.5), 7: (0.7, 0.5),
        2: (-0.5, 0.5), 6: (1.5, 0.5), 10: (0.5, 1.5), 9: (0.3, 1.5), 12: (0.7, 1.5),
    },
    "three_models": {
        0: (0.5, 0.5), 4: (0.5, 0.5), 3: (0.25, 0.5), 7: (0.75, 0.5),
        2: (-0.5, 0.5), 6: (1.5, 0.5), 10: (0.5, 1.5), 9: (0.25, 1.5), 12: (0.75, 1.5),
    },
}
LAYOUT_SCALE = {"normal": 2.1, "three_models": 1.8}
OFFSCREEN = {2, 6, 9, 10, 12}

# CharacterLayoutDepthType: Top=0, MidTop=1, MidBack=2, Back=3. Rows further back are
# drawn first and slightly smaller. The game's exact per-row scale is not documented
# anywhere we can check against — sekai-viewer ignores DepthType outright — so the
# ladder is a geometric step, tunable, and every non-zero DepthType is logged. Event 1
# never uses one (all 778 LayoutData rows are Top), so nothing here depends on it.
DEPTH_STEP = 0.94


def depth_scale(depth: int, step: float = DEPTH_STEP) -> float:
    return step ** max(0, int(depth or 0))

def _get(url: str, timeout: int = 60):
    """GET with retries. A single dropped connection used to abort an entire render:
    a full build makes thousands of these, so a transient proxy failure is expected
    rather than exceptional."""
    last: Exception | None = None
    for attempt in range(4):
        try:
            return _session.get(url, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - proxy/DNS/reset, all worth retrying
            last = exc
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]


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
    }
)


# --- offscreen GL ------------------------------------------------------------


def make_legacy_context() -> None:
    """Current-thread offscreen GL 2.1 context via CGL.

    A core 3.3 context (what moderngl gives you) rejects Cubism's ``#version 120``
    shaders, so the renderer silently draws nothing — hence the legacy profile.
    """
    cgl = ctypes.CDLL(ctypes.util.find_library("OpenGL"))
    attrs = (c_int * 11)(99, 0x1000, 8, 24, 11, 8, 12, 24, 73, 0, 0)
    pix, npix, ctx = c_void_p(), c_int(), c_void_p()
    if cgl.CGLChoosePixelFormat(attrs, byref(pix), byref(npix)) or not npix.value:
        raise RuntimeError("no legacy CGL pixel format")
    if cgl.CGLCreateContext(pix, None, byref(ctx)):
        raise RuntimeError("CGLCreateContext failed")
    cgl.CGLSetCurrentContext(ctx)


# --- asset fetching ----------------------------------------------------------


def model_dir(costume: str) -> Path | None:
    """Download + decrypt ``live2d/model/<costume>`` and return its extract dir."""
    dest = CACHE / "models" / costume
    marker = dest / ".ok"
    if marker.exists():
        return dest
    if (dest / ".missing").exists():
        return None
    dest.mkdir(parents=True, exist_ok=True)
    url = (
        "https://n-production-846c90c1-assetbundle.sekai-en.com/"
        "5.5.1.20/5ea006ba-5840-4fe4-aed8-d1beeacd39ab/android/"
        f"live2d/model/{costume}"
    )
    resp = _get(url, timeout=120)
    if resp.status_code != 200:
        (dest / ".missing").touch()
        return None
    blob = CACHE / "bundles" / f"{costume}.bin"
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(resp.content)
    subprocess.run(
        [str(SSSEKAI_PY), "live2dextract", str(blob), str(dest)],
        check=True,
        capture_output=True,
    )
    marker.touch()
    return dest


unresolved_motion_bases: set[str] = set()


def motion_base(costume: str) -> str | None:
    """Locate a costume's motion directory on the mirror, or ``None``.

    ``01ichika_cloth001`` → ``v1/main/01_ichika/01ichika_motion_base``

    Remade models carry a version marker, and it appears in *both* the directory and
    the base name — ``v2_08shizuku_casual`` lives at
    ``v2/main/08_shizuku/v2_08shizuku_motion_base``, not at the v1 path. Splitting on
    ``_`` and taking the first field reads the marker as the character, probes a
    nonsense path, finds nothing, and the model renders in its rest pose: arms out,
    unmistakably a T-pose in the middle of a scene.

    Sub-characters (``sub_*``) have no motion set published under any path tried, so
    they legitimately resolve to None. Both cases land in
    ``unresolved_motion_bases`` so a caller can report them rather than silently
    shipping a T-pose.
    """
    import re

    parts = costume.split("_")
    marker = parts.pop(0) if parts and re.fullmatch(r"v\d+", parts[0]) else ""
    core = parts[0] if parts else ""
    digits = "".join(ch for ch in core[:2] if ch.isdigit())
    name = core[len(digits) :]
    if not digits or not name:
        unresolved_motion_bases.add(costume)
        return None

    key = f"{marker}_{core}" if marker else core
    cache = CACHE / "motion_base.json"
    known = json.loads(cache.read_text()) if cache.exists() else {}
    if key in known:
        if not known[key]:
            unresolved_motion_bases.add(costume)
        return known[key] or None

    if marker:
        candidates = [f"{marker}/main/{digits}_{name}/{marker}_{core}_motion_base"]
    else:
        candidates = [f"{version}/main/{digits}_{name}/{core}_motion_base" for version in ("v1", "v2")]
    found = None
    for candidate in candidates:
        try:
            probe = _session.head(f"{LIVE2D_CDN}/motion/{candidate}/BuildMotionData.json", timeout=45)
        except Exception:  # noqa: BLE001
            time.sleep(2)
            continue
        if probe.status_code == 200:
            found = candidate
            break
    if not found:
        unresolved_motion_bases.add(costume)
    known[key] = found
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(known, indent=1))
    return found


def motion_json(costume: str, kind: str, name: str) -> dict | None:
    """``kind`` is ``motion`` (body) or ``facial`` (expression)."""
    if not name:
        return None
    base = motion_base(costume)
    if not base:
        return None
    dest = CACHE / "motions" / base / kind / f"{name}.motion3.json"
    if dest.exists():
        return json.loads(dest.read_text()) if dest.stat().st_size else None
    dest.parent.mkdir(parents=True, exist_ok=True)
    resp = _get(f"{LIVE2D_CDN}/motion/{base}/{kind}/{name}.motion3.json")
    if resp.status_code != 200:
        dest.write_text("")
        return None
    dest.write_bytes(resp.content)
    return resp.json()


# --- motion3 curve evaluation ------------------------------------------------


def eval_curve(curve: dict, time: float) -> float:
    """Value of one motion3 curve at ``time`` (linear/bezier/stepped segments)."""
    points = curve["Segments"]
    x0, y0 = points[0], points[1]
    idx = 2
    value = y0
    while idx < len(points):
        seg_type = int(points[idx])
        idx += 1
        if seg_type == 0:  # linear
            x1, y1 = points[idx], points[idx + 1]
            idx += 2
            if time <= x1:
                span = x1 - x0
                t = 0.0 if span <= 0 else (time - x0) / span
                return y0 + (y1 - y0) * t
            x0, y0 = x1, y1
        elif seg_type == 1:  # cubic bezier
            cx1, cy1, cx2, cy2, x1, y1 = points[idx : idx + 6]
            idx += 6
            if time <= x1:
                span = x1 - x0
                t = 0.0 if span <= 0 else (time - x0) / span
                u = 1 - t
                return (
                    u**3 * y0 + 3 * u**2 * t * cy1 + 3 * u * t**2 * cy2 + t**3 * y1
                )
            x0, y0 = x1, y1
        elif seg_type in (2, 3):  # stepped / inverse-stepped
            x1, y1 = points[idx], points[idx + 1]
            idx += 2
            if time <= x1:
                return y0 if seg_type == 2 else y1
            x0, y0 = x1, y1
        else:  # unknown segment kind — stop rather than mis-read the buffer
            break
        value = y0
    return value


def settle_time(data: dict | None, tolerance: float = 1e-3) -> float:
    """Earliest time from which every curve in ``data`` is already constant.

    Sekai talk motions are "move into the pose and hold": the last third or so of
    every curve is flat, so any sample taken after this point is the pose the player
    actually reads the line against. Returns 0.0 for an absent/empty motion.
    """
    if not data:
        return 0.0
    duration = float(data.get("Meta", {}).get("Duration", 0) or 0)
    latest = 0.0
    for curve in data.get("Curves", []):
        points = curve.get("Segments") or []
        if len(points) < 2:
            continue
        # walk segments backwards, keeping the earliest x whose value still matches
        # the final value
        try:
            final = eval_curve(curve, duration)
        except Exception:  # noqa: BLE001 - malformed curve
            continue
        lo, hi = 0.0, duration
        for _ in range(24):  # bisect: first time the curve has reached its final value
            mid = (lo + hi) / 2
            try:
                flat = abs(eval_curve(curve, mid) - final) <= tolerance
            except Exception:  # noqa: BLE001
                break
            if flat:
                hi = mid
            else:
                lo = mid
        latest = max(latest, hi)
    return latest


def apply_motion(model, data: dict | None, time: float | None = None) -> None:
    """Push a motion3's parameter/opacity values at ``time`` into the model.

    ``time`` is absolute seconds; ``None`` means the settled end pose.
    """
    if not data:
        return
    duration = float(data.get("Meta", {}).get("Duration", 0) or 0)
    # default to the settled end pose: Sekai talk motions resolve into the pose the
    # frame is meant to show, whereas t=0 is still the previous pose
    when = duration if time is None else max(0.0, min(time, duration))
    for curve in data.get("Curves", []):
        target, cid = curve.get("Target"), curve.get("Id")
        try:
            value = eval_curve(curve, when)
        except Exception:  # noqa: BLE001 - malformed curve, skip it
            continue
        if target == "Parameter":
            try:
                model.SetParameterValue(cid, value, 1.0)
            except Exception:  # noqa: BLE001 - parameter absent on this model
                pass
        elif target == "PartOpacity":
            try:
                model.SetPartOpacity(cid, value)
            except Exception:  # noqa: BLE001
                pass


# --- rendering ---------------------------------------------------------------


class Live2DStage:
    """Owns the GL context + model cache; renders one character at a time.

    The cache is bounded. Every loaded model holds native Cubism state and GL
    textures, and keeping them all alive segfaults the native layer once a run spans
    enough costumes — a full catalogue render died with SIGSEGV at 91 models.
    sekai-viewer bounds it the same way (``Live2DController.model_queue`` "replaces
    the oldest model").

    Eviction is barely felt in practice: sprites are rendered in sorted key order and
    the key starts with the costume, so all of a costume's poses are drawn together.
    """

    MAX_MODELS = 6

    def __init__(self, size: tuple[int, int] = (1100, 1100)) -> None:
        import live2d.v3 as live2d
        from OpenGL.GL import (
            GL_COLOR_ATTACHMENT0,
            GL_FRAMEBUFFER,
            GL_RGBA,
            GL_RGBA8,
            GL_TEXTURE_2D,
            GL_UNSIGNED_BYTE,
            glBindFramebuffer,
            glBindTexture,
            glFramebufferTexture2D,
            glGenFramebuffers,
            glGenTextures,
            glTexImage2D,
        )

        make_legacy_context()
        self.live2d = live2d
        self.size = size
        live2d.init()
        live2d.glInit()
        self.fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        tex = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, size[0], size[1], 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
        # insertion-ordered: the oldest live model is the first non-None entry
        self._models: dict[str, object] = {}

    def _evict(self) -> None:
        """Drop the least recently loaded model, releasing its renderer."""
        for key, model in list(self._models.items()):
            if model is None:
                continue  # a "missing" marker costs nothing, keep it
            try:
                model.DestroyRenderer()
            except Exception:  # noqa: BLE001 - already gone; dropping the ref is enough
                pass
            del self._models[key]
            return

    def model(self, costume: str):
        if costume in self._models:
            # refresh recency so a costume in active use is not the next evicted
            self._models[costume] = self._models.pop(costume)
            return self._models[costume]
        directory = model_dir(costume)
        if not directory:
            self._models[costume] = None
            return None
        model3 = next(directory.glob("*.model3.json"), None)
        if not model3:
            self._models[costume] = None
            return None
        live = sum(1 for m in self._models.values() if m is not None)
        while live >= self.MAX_MODELS:
            self._evict()
            live -= 1
        model = self.live2d.LAppModel()
        model.LoadModelJson(str(model3))
        model.Resize(*self.size)
        model.SetAutoBlinkEnable(False)
        model.SetAutoBreathEnable(False)
        self._models[costume] = model
        return model

    def render(
        self,
        costume: str,
        motion: str,
        facial: str,
        scale: float,
        offset_y: float,
        offset_x: float = 0.0,
        flip: bool = False,
        pose_time: float | None = None,
    ):
        """One character, posed, as an RGBA image (transparent background).

        ``scale`` 1.0 draws the model canvas exactly one viewport-height tall, so the
        game's ``* 2.1`` multiplier can be passed straight through. Offsets are in
        units of half the viewport height (measured), +y up, +x right.

        ``flip`` mirrors the model: the draw is done at the mirrored x offset and the
        whole stage-sized buffer is then flipped, which puts the model back at its
        intended x while reversing the art. ``pose_time`` is absolute seconds into
        the motion; ``None`` samples the settled end pose.
        """
        from OpenGL.GL import (
            GL_COLOR_BUFFER_BIT,
            GL_FRAMEBUFFER,
            GL_RGBA,
            GL_UNSIGNED_BYTE,
            glBindFramebuffer,
            glClear,
            glClearColor,
            glReadPixels,
            glViewport,
        )

        model = self.model(costume)
        if model is None:
            return None
        body = motion_json(costume, "motion", motion)
        face = motion_json(costume, "facial", facial)
        model.ResetParameters()
        model.SetScale(scale)
        model.SetOffset(-offset_x if flip else offset_x, offset_y)
        apply_motion(model, body, pose_time)
        apply_motion(model, face, pose_time)
        model.Update()
        apply_motion(model, body, pose_time)
        apply_motion(model, face, pose_time)

        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, *self.size)
        glClearColor(0, 0, 0, 0)
        glClear(GL_COLOR_BUFFER_BIT)
        model.Draw()
        buf = glReadPixels(0, 0, self.size[0], self.size[1], GL_RGBA, GL_UNSIGNED_BYTE)
        sprite = Image.frombytes("RGBA", self.size, buf).transpose(Image.FLIP_TOP_BOTTOM)
        return sprite.transpose(Image.FLIP_LEFT_RIGHT) if flip else sprite


# --- scenario state ----------------------------------------------------------


def _first_layout_rows(scenario: dict) -> list[dict]:
    """``FirstLayout`` as equivalent ``Appear`` LayoutData rows.

    The game seeds the stage from ``FirstLayout`` before the first snippet runs;
    sekai-viewer's loader does it by synthesising Appear rows, and so do we, so the
    walk below has a single code path.
    """
    rows = []
    for entry in scenario.get("FirstLayout") or []:
        side = entry.get("PositionSide", 4)
        rows.append(
            {
                "Type": 2,  # Appear
                "SideFrom": side,
                "SideFromOffsetX": entry.get("OffsetX", 0.0),
                "SideTo": side,
                "SideToOffsetX": entry.get("OffsetX", 0.0),
                "DepthType": 0,
                "Character2dId": entry.get("Character2dId"),
                "CostumeType": entry.get("CostumeType", ""),
                "MotionName": entry.get("MotionName", ""),
                "FacialName": entry.get("FacialName", ""),
            }
        )
    return rows


def stage_states(scenario: dict) -> dict[int, list[dict]]:
    """Talk index → characters on stage, each with costume/motion/facial/position.

    Walks the snippet list the way the game does: ``CharacterLayout`` (2) and
    ``CharacterMotion`` (4) mutate stage state, ``Talk`` (1) snapshots it, and the
    talk's own ``Motions`` override the speaker's pose for that line.

    Only ``Appear`` (2) reveals a model and only ``Clear`` (3) hides one. A bare
    motion does not: the game keeps a hidden model's alpha at 0 and merely flips an
    internal visible flag, so treating ``CharacterMotion``/``Motion`` as a reveal puts
    characters on stage who are not in the frame.
    """
    layouts = scenario.get("LayoutData") or []
    talks = scenario.get("TalkData") or []
    state: dict[int, dict] = {}
    out: dict[int, list[dict]] = {}

    def apply(layout: dict) -> None:
        cid = layout.get("Character2dId")
        if cid is None:
            return
        entry = state.setdefault(
            cid,
            {
                "costume": "",
                "motion": "",
                "facial": "",
                "side": 4,
                "offset_x": 0.0,
                "depth": 0,
                "visible": False,
            },
        )
        if layout.get("CostumeType"):
            entry["costume"] = layout["CostumeType"]
        if layout.get("MotionName"):
            entry["motion"] = layout["MotionName"]
        if layout.get("FacialName"):
            entry["facial"] = layout["FacialName"]
        entry["depth"] = layout.get("DepthType", 0) or 0
        layout_type = layout.get("Type")
        if layout_type == 3:  # Clear
            entry["visible"] = False
            return
        # Only Motion (1) and Appear (2) reposition. CharacterMotion (0) is
        # "apply motion or expression only" — its SideFrom/SideTo are not a move
        # instruction and the game's own player ignores them. Honouring them
        # teleports characters on top of each other (e.g. event_01_02 talk 27,
        # where a bare motion row carries SideTo=Left for someone standing Right).
        if layout_type in (1, 2):
            side_to = layout.get("SideTo", 0)
            if side_to:
                entry["side"] = side_to
                entry["offset_x"] = layout.get("SideToOffsetX", 0.0) or 0.0
        if layout_type == 2:  # Appear
            entry["visible"] = True

    for row in _first_layout_rows(scenario):
        apply(row)

    for snippet in scenario.get("Snippets") or []:
        action = snippet.get("Action")
        ref = snippet.get("ReferenceIndex", 0)
        if action in (2, 4) and ref < len(layouts):
            apply(layouts[ref])
        elif action == 1:
            snapshot = {
                cid: dict(entry) for cid, entry in state.items() if entry["visible"] and entry["costume"]
            }
            talk = talks[ref] if ref < len(talks) else {}
            for motion in talk.get("Motions") or []:
                cid = motion.get("Character2dId")
                if cid in snapshot:
                    if motion.get("MotionName"):
                        snapshot[cid]["motion"] = motion["MotionName"]
                    if motion.get("FacialName"):
                        snapshot[cid]["facial"] = motion["FacialName"]
            speakers = {c.get("Character2dId") for c in (talk.get("TalkCharacters") or [])}
            out[ref] = [
                {"character2d_id": cid, "speaking": cid in speakers, **entry}
                for cid, entry in snapshot.items()
            ]
    return out


# SpecialEffectType values that change what a still frame of a talk line looks like.
CHANGE_BACKGROUND = 7
FLASHBACK_IN, FLASHBACK_OUT = 9, 10
CHANGE_CARD_STILL, CHANGE_BACKGROUND_STILL = 11, 17
AMBIENT = {12: "normal", 13: "evening", 14: "night"}
# fade-to-colour pairs: the "out" covers the screen, the "in" clears it again
COVER_OUT = {2: "black", 4: "white", 21: "white"}
COVER_IN = {1, 3, 20}
# live2d ambient colour grades, from sekai-viewer's AmbientColor* effects:
# per-channel multiply followed by saturate(-0.1)
AMBIENT_GRADE = {
    "normal": ((1.0, 1.0, 1.0), 1.0),
    "evening": ((0.9, 0.9, 0.8), 0.9333),
    "night": ((0.85, 0.85, 0.9), 0.9333),
}


def scene_states(scenario: dict) -> dict[int, dict]:
    """Talk index → everything except the cast that decides how the frame looks.

    Walks ``SpecialEffectData`` alongside the talks, tracking the state each effect
    leaves behind: the live background, a card/background still covering it, the
    flashback dim, the live2d ambient grade, and whether a fade has left the screen
    covered. Effects that are transient by construction (Telop, PlaceInfo, shakes,
    scenario effects) never survive to a talk — the game hides them as the next talk
    opens — so they are deliberately not tracked.
    """
    effects = scenario.get("SpecialEffectData") or []
    state = {
        "background": scenario.get("FirstBackground") or "",
        "still": "",
        "flashback": False,
        "ambient": "normal",
        "cover": "",
    }
    out: dict[int, dict] = {}
    for snippet in scenario.get("Snippets") or []:
        action = snippet.get("Action")
        ref = snippet.get("ReferenceIndex", 0)
        if action == 6 and ref < len(effects):
            effect = effects[ref]
            kind = effect.get("EffectType")
            value = effect.get("StringValSub") or effect.get("StringVal") or ""
            if kind == CHANGE_BACKGROUND and value:
                state["background"], state["still"] = value, ""
            elif kind in (CHANGE_CARD_STILL, CHANGE_BACKGROUND_STILL):
                state["still"] = value
            elif kind == FLASHBACK_IN:
                state["flashback"] = True
            elif kind == FLASHBACK_OUT:
                state["flashback"] = False
            elif kind in AMBIENT:
                state["ambient"] = AMBIENT[kind]
            elif kind in COVER_OUT:
                state["cover"] = COVER_OUT[kind]
            elif kind in COVER_IN:
                state["cover"] = ""
        elif action == 1:
            out[ref] = dict(state)
    return out


def grade(sprite: Image.Image, ambient: str) -> Image.Image:
    """Apply a live2d ambient colour grade to one character sprite."""
    (mr, mg, mb), sat = AMBIENT_GRADE.get(ambient, AMBIENT_GRADE["normal"])
    if (mr, mg, mb, sat) == (1.0, 1.0, 1.0, 1.0):
        return sprite
    from PIL import ImageEnhance

    red, green, blue, alpha = sprite.split()
    red = red.point(lambda v: min(255, round(v * mr)))
    green = green.point(lambda v: min(255, round(v * mg)))
    blue = blue.point(lambda v: min(255, round(v * mb)))
    rgb = ImageEnhance.Color(Image.merge("RGB", (red, green, blue))).enhance(sat)
    return Image.merge("RGBA", (*rgb.split(), alpha))


def compose_scene(
    stage: Live2DStage,
    background: Image.Image,
    characters: list[dict],
    layout_mode: str = "normal",
    flip_ids: set[int] | None = None,
    pose_time: float | None = None,
    ambient: str = "normal",
    depth_step: float = DEPTH_STEP,
) -> Image.Image:
    """Draw every on-stage character over the background, using the game's transform.

    No hand-tuned framing: each model is drawn at ``LAYOUT_SCALE`` (2.1 normal /
    1.8 three-model — the same multiplier the viewer uses over
    ``stage_height / originalHeight``) with its canvas centre placed at
    ``(stage_w * pos.x, stage_h * (pos.y + 0.3))``.

    ``stage`` must have been created at the background's size, since the model is
    rendered straight into stage-sized pixels rather than resized afterwards.
    """
    canvas = background.convert("RGBA")
    width, height = canvas.size
    positions = POSITION_MAPS[layout_mode]
    scale = LAYOUT_SCALE[layout_mode]
    flip_ids = flip_ids or set()
    onstage = [c for c in characters if c["side"] not in OFFSCREEN]
    # deepest row first, then non-speakers, so the speaker lands on top
    onstage.sort(key=lambda c: (-c.get("depth", 0), c["speaking"], -c["side"]))
    for char in onstage:
        pos_x, pos_y = positions.get(char["side"], (0.5, 0.5))
        pos_x += char.get("offset_x", 0.0) / 1920  # SideToOffsetX, as the viewer does
        # offsets are in units of half the viewport height, +y up
        offset_x = (pos_x - 0.5) * width / (height / 2)
        offset_y = -((pos_y + 0.3) - 0.5) * height / (height / 2)
        sprite = stage.render(
            char["costume"],
            char["motion"],
            char["facial"],
            scale * depth_scale(char.get("depth", 0), depth_step),
            offset_y,
            offset_x,
            flip=char["character2d_id"] in flip_ids,
            pose_time=pose_time,
        )
        if sprite is None:
            continue
        sprite = grade(sprite, ambient)
        if sprite.size != canvas.size:
            sprite = sprite.resize(canvas.size, Image.LANCZOS)
        canvas.alpha_composite(sprite)
    return canvas
