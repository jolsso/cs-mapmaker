"""Offscreen OpenGL rendering of a Mesh (moderngl; EGL/Mesa in the container)."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import moderngl
import numpy as np

from mapforge.bsp.reader import Bsp
from mapforge.render.mesh import Mesh
from mapforge.render.textures import WadIndex, texture_rgba

VERTEX = """
#version 330
uniform mat4 mvp;
in vec3 in_pos;
in vec2 in_uv;
in vec2 in_luv;
out vec2 uv;
out vec2 luv;
out vec3 world;
void main() {
    gl_Position = mvp * vec4(in_pos, 1.0);
    uv = in_uv; luv = in_luv; world = in_pos;
}
"""

FRAGMENT = """
#version 330
uniform sampler2D tex;
uniform sampler2D lightmap;
uniform sampler2D clipmap;     // top-down only: max visible z per (x, y)
uniform vec4 clip_rect;        // x0, y0, x1, y1 of the clipmap in world units
uniform int use_clip;
uniform float light_gamma;
uniform float light_scale;
uniform int light_only;
in vec2 uv;
in vec2 luv;
in vec3 world;
out vec4 color;
void main() {
    if (use_clip == 1) {
        vec2 c = (world.xy - clip_rect.xy) / (clip_rect.zw - clip_rect.xy);
        if (world.z > texture(clipmap, c).r) discard;
    }
    vec4 t = texture(tex, uv);
    if (t.a < 0.5) discard;
    vec3 l = pow(texture(lightmap, luv).rgb, vec3(1.0 / light_gamma)) * light_scale;
    color = vec4(light_only == 1 ? min(l, 1.0) : min(t.rgb * l, 1.0), 1.0);
}
"""


@dataclass
class Camera:
    """View-projection matrix (column-major for GL) and image size."""

    mvp: np.ndarray
    width: int
    height: int


def ortho_top_down(lo: np.ndarray, hi: np.ndarray, width: int, height: int) -> Camera:
    """Looking straight down; world x -> image right, world y -> image up (north up)."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    proj = np.array(
        [
            [2 / (x1 - x0), 0, 0, -(x1 + x0) / (x1 - x0)],
            [0, 2 / (y1 - y0), 0, -(y1 + y0) / (y1 - y0)],
            [0, 0, 2 / (z1 - z0), -(z1 + z0) / (z1 - z0)],  # higher z is nearer
            [0, 0, 0, 1],
        ]
    )
    return Camera(mvp=proj, width=width, height=height)


def look_at(eye: np.ndarray, target: np.ndarray, fov_deg: float, width: int, height: int,
            near: float = 4.0, far: float = 16384.0) -> Camera:  # fmt: skip
    """Perspective camera (z is up, as in GoldSrc)."""
    f = target - eye
    f = f / np.linalg.norm(f)
    up = np.array([0.0, 0.0, 1.0])
    if abs(f @ up) > 0.999:
        up = np.array([0.0, 1.0, 0.0])
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    view = np.eye(4)
    view[0, :3], view[1, :3], view[2, :3] = s, u, -f
    view[:3, 3] = -view[:3, :3] @ eye
    aspect = width / height
    t = 1 / np.tan(np.radians(fov_deg) / 2)
    proj = np.array(
        [
            [t / aspect, 0, 0, 0],
            [0, t, 0, 0],
            [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
            [0, 0, -1, 0],
        ]
    )
    return Camera(mvp=proj @ view, width=width, height=height)


def create_context() -> moderngl.Context:
    if sys.platform.startswith("linux"):
        return moderngl.create_standalone_context(
            backend="egl", libgl="libGL.so.1", libegl="libEGL.so.1"
        )
    return moderngl.create_standalone_context()


class Renderer:
    """Uploads a mesh once; renders any number of cameras to RGB arrays."""

    def __init__(self, bsp: Bsp, mesh: Mesh, wads: WadIndex, ctx: moderngl.Context | None = None,
                 light_gamma: float = 1.6, light_scale: float = 1.15) -> None:  # fmt: skip
        self.ctx = ctx or create_context()
        self.prog = self.ctx.program(vertex_shader=VERTEX, fragment_shader=FRAGMENT)
        self.prog["light_gamma"].value = light_gamma
        self.prog["light_scale"].value = light_scale
        self.prog["use_clip"].value = 0
        self.lightmap = self.ctx.texture(mesh.atlas.shape[1::-1], 3, mesh.atlas.tobytes())
        self.lightmap.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.texture_sources: dict[str, str] = {}
        self.draws = []
        for tex_index, verts in mesh.batches.items():
            rgba, source = texture_rgba(bsp, tex_index, wads)
            self.texture_sources[bsp.textures[tex_index].name] = source
            t = self.ctx.texture(rgba.shape[1::-1], 4, np.ascontiguousarray(rgba).tobytes())
            t.build_mipmaps()
            t.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.NEAREST)
            t.repeat_x = t.repeat_y = True
            vbo = self.ctx.buffer(verts.tobytes())
            vao = self.ctx.vertex_array(self.prog, [(vbo, "3f 2f 2f", "in_pos", "in_uv", "in_luv")])
            self.draws.append((t, vao))
        self.clip_tex = self.ctx.texture(
            (1, 1), 1, np.array([1e9], dtype="f4").tobytes(), dtype="f4"
        )

    def set_clipmap(self, clip: np.ndarray | None, rect: tuple[float, float, float, float]) -> None:
        """Per-(x, y) max visible z for top-down renders; None disables clipping."""
        if clip is None:
            self.prog["use_clip"].value = 0
            return
        self.clip_tex = self.ctx.texture(
            clip.shape[1::-1], 1, np.ascontiguousarray(clip, dtype="f4").tobytes(), dtype="f4"
        )
        self.clip_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.prog["use_clip"].value = 1
        self.prog["clip_rect"].value = rect

    def render(
        self, cam: Camera, light_only: bool = False, background=(0.06, 0.06, 0.07)
    ) -> np.ndarray:
        fbo = self.ctx.simple_framebuffer((cam.width, cam.height), samples=0)
        fbo.use()
        self.ctx.enable(moderngl.DEPTH_TEST)
        self.ctx.disable(moderngl.CULL_FACE)
        self.ctx.clear(*background, depth=1.0)
        self.prog["mvp"].write(cam.mvp.T.astype("f4").tobytes())
        self.prog["light_only"].value = 1 if light_only else 0
        self.prog["tex"].value = 0
        self.prog["lightmap"].value = 1
        self.prog["clipmap"].value = 2
        self.lightmap.use(1)
        self.clip_tex.use(2)
        for t, vao in self.draws:
            t.use(0)
            vao.render(moderngl.TRIANGLES)
        img = np.frombuffer(fbo.read(components=3), dtype=np.uint8)
        img = img.reshape(cam.height, cam.width, 3)[::-1]  # GL origin is bottom-left
        fbo.release()
        return img.copy()
