"""Render one known sprite and assert it is not blank.

A GL context that accepts Cubism's #version 120 shaders and then draws nothing is the
failure this is guarding against, so success is measured in pixels, not exit codes.
"""
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
from live2d_scene import Live2DStage  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "run"
COSTUME, MOTION, FACIAL = "01ichika_cloth001", "w-cool-nod03", "face_smile_02"

stage = Live2DStage(size=(640, 360))
image = stage.render(COSTUME, MOTION, FACIAL, 2.1, -0.6, 0.0)
if image is None:
    raise SystemExit(f"[{label}] render returned None — the model would not load")

opaque = sum(1 for pixel in image.getdata() if pixel[3] > 8)
image.save(f"spike-{label}.png")
print(f"[{label}] {opaque} non-transparent pixels, bbox {image.getbbox()}")

# the Mac reference for this exact pose draws ~34,500 of 230,400
if opaque < 10000:
    raise SystemExit(f"[{label}] BLANK FRAME — context accepted the shaders but drew nothing")
print(f"[{label}] OK — drew real content")
