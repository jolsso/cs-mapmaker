"""Top-down (overview) renders: orthographic, roofs cut away above the players' heads."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from mapforge.bsp.reader import Bsp
from mapforge.render.gl import Renderer, ortho_top_down
from mapforge.validate.checks import spawn_origins
from mapforge.validate.walk import WalkGraph, bomb_sites, site_labels

T_COLOR = (230, 90, 40)
CT_COLOR = (60, 140, 235)
SITE_COLOR = (250, 210, 60)


@dataclass(frozen=True)
class TopDownView:
    """World <-> pixel mapping of a top-down image (for overlays and heatmaps)."""

    x0: float
    y0: float
    x1: float
    y1: float
    width: int
    height: int

    def to_px(self, xy: np.ndarray) -> np.ndarray:
        xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        px = (xy[:, 0] - self.x0) / (self.x1 - self.x0) * self.width
        py = (self.y1 - xy[:, 1]) / (self.y1 - self.y0) * self.height
        return np.column_stack([px, py])

    @property
    def units_per_px(self) -> float:
        return (self.x1 - self.x0) / self.width

    def to_dict(self) -> dict:
        return {
            "world_rect": [self.x0, self.y0, self.x1, self.y1],
            "size": [self.width, self.height],
            "units_per_px": round(self.units_per_px, 3),
        }


def view_for(graph: WalkGraph, max_px: int = 2048, margin: float = 192) -> TopDownView:
    lo = graph.feet[:, :2].min(axis=0) - margin
    hi = graph.feet[:, :2].max(axis=0) + margin
    size = hi - lo
    scale = max_px / size.max()
    w, h = max(64, int(size[0] * scale)), max(64, int(size[1] * scale))
    return TopDownView(lo[0], lo[1], lo[0] + w / scale, lo[1] + h / scale, w, h)


def clipmap(graph: WalkGraph, view: TopDownView, res: float = 32, above: float = 112,
            dilate: int = 3) -> tuple[np.ndarray, tuple[float, float, float, float]]:  # fmt: skip
    """Max visible z per (x, y) cell: highest feet z there + `above`; -inf away from play."""
    nx = int(np.ceil((view.x1 - view.x0) / res))
    ny = int(np.ceil((view.y1 - view.y0) / res))
    clip = np.full((ny, nx), -1e9, dtype=np.float32)
    ix = np.clip(((graph.feet[:, 0] - view.x0) / res).astype(int), 0, nx - 1)
    iy = np.clip(((graph.feet[:, 1] - view.y0) / res).astype(int), 0, ny - 1)
    np.maximum.at(clip, (iy, ix), (graph.feet[:, 2] + above).astype(np.float32))
    for _ in range(dilate):  # grow into walls next to the play area so they are drawn
        grown = clip.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                grown = np.maximum(grown, np.roll(np.roll(clip, dy, 0), dx, 1))
        clip = np.where(clip > -1e8, clip, grown)
    return clip, (view.x0, view.y0, view.x0 + nx * res, view.y0 + ny * res)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except OSError:
        return ImageFont.load_default()


def annotate(img: np.ndarray, view: TopDownView, bsp: Bsp, title: str) -> Image.Image:
    """Spawns (T orange, CT blue), bomb sites (yellow boxes), scale bar and north arrow."""
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    font, small = _font(max(14, view.width // 80)), _font(max(11, view.width // 120))
    origins, teams = spawn_origins(bsp.entities)
    r = max(3, int(24 / view.units_per_px))
    for (px, py), team in zip(view.to_px(origins[:, :2]), teams, strict=True):
        c = T_COLOR if team == "T" else CT_COLOR
        d.ellipse([px - r, py - r, px + r, py + r], fill=c, outline=(0, 0, 0))
    labels = site_labels(bsp)
    for n, boxes in enumerate(bomb_sites(bsp), start=1):
        lo = np.min([b[0] for b in boxes], axis=0)
        hi = np.max([b[1] for b in boxes], axis=0)
        (ax, ay), (bx, by) = view.to_px(np.array([[lo[0], hi[1]], [hi[0], lo[1]]]))
        d.rectangle([ax, ay, bx, by], outline=SITE_COLOR, width=max(2, view.width // 600))
        d.text((ax + 4, ay + 2), f"site {labels[n - 1]}", fill=SITE_COLOR, font=font,
               stroke_width=2, stroke_fill=(0, 0, 0))  # fmt: skip
    # scale bar (512 units) and north arrow
    bar = 512 / view.units_per_px
    x, y = 20, view.height - 30
    d.rectangle([x, y, x + bar, y + 6], fill=(240, 240, 240), outline=(0, 0, 0))
    d.text((x, y - 22), "512 units", fill=(240, 240, 240), font=small, stroke_width=2,
           stroke_fill=(0, 0, 0))  # fmt: skip
    d.text((view.width - 40, 12), "N", fill=(240, 240, 240), font=font, stroke_width=2,
           stroke_fill=(0, 0, 0))  # fmt: skip
    d.text((20, 12), title, fill=(240, 240, 240), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
    return im


def draw_zones(im: Image.Image, view: TopDownView, zones: list[dict]) -> Image.Image:
    """Red outlines + area labels for zones from brightness.dark_zones()."""
    d = ImageDraw.Draw(im)
    font = _font(max(11, view.width // 120))
    for n, z in enumerate(zones, start=1):
        (lo, hi) = z["bbox"]
        (ax, ay), (bx, by) = view.to_px(np.array([[lo[0] - 8, hi[1] + 8], [hi[0] + 8, lo[1] - 8]]))
        d.rectangle([ax, ay, bx, by], outline=(235, 40, 40), width=max(2, view.width // 700))
        d.text((ax + 3, ay + 2), f"dark {n}", fill=(255, 90, 90), font=font, stroke_width=2,
               stroke_fill=(0, 0, 0))  # fmt: skip
    return im


def render_topdown(renderer: Renderer, bsp: Bsp, graph: WalkGraph, z_range: tuple[float, float],
                   max_px: int = 2048) -> tuple[np.ndarray, np.ndarray, TopDownView]:  # fmt: skip
    """(textured+lit image, light-only image, view) seen from straight above."""
    view = view_for(graph, max_px)
    clip, rect = clipmap(graph, view)
    renderer.set_clipmap(clip, rect)
    cam = ortho_top_down(
        np.array([view.x0, view.y0, z_range[0] - 64]),
        np.array([view.x1, view.y1, z_range[1] + 64]),
        view.width,
        view.height,
    )
    lit = renderer.render(cam)
    light = renderer.render(cam, light_only=True)
    renderer.set_clipmap(None, (0, 0, 1, 1))
    return lit, light, view
