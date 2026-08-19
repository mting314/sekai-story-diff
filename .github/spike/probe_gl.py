"""Report what OpenGL the runner can actually give us."""
import glfw

if not glfw.init():
    raise SystemExit("glfw.init() failed")
glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)
glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 1)
window = glfw.create_window(64, 64, "probe", None, None)
if not window:
    raise SystemExit("could not create a 2.1 context")
glfw.make_context_current(window)

from OpenGL.GL import GL_RENDERER, GL_SHADING_LANGUAGE_VERSION, GL_VENDOR, GL_VERSION, glGetString

for label, enum in (("vendor", GL_VENDOR), ("renderer", GL_RENDERER),
                    ("version", GL_VERSION), ("glsl", GL_SHADING_LANGUAGE_VERSION)):
    value = glGetString(enum)
    print(f"  {label:9s} {value.decode() if value else '(null)'}")
