"""Heatmap overlays on the raw top-down render (used by analysis, phase 5)."""

from __future__ import annotations

import numpy as np
from PIL import Image

from mapforge.render.topdown import TopDownView

# Perceptually ordered ramp (dark purple -> yellow), sampled from the "inferno" family.
RAMP = np.array(
    [[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21],
     [250, 193, 39], [252, 255, 164]],
    dtype=np.float64,
)  # fmt: skip


def density(view: TopDownView, xy: np.ndarray, weights: np.ndarray | None = None,
            sigma_units: float = 64) -> np.ndarray:  # fmt: skip
    """(h, w) density of world points, Gaussian-smoothed with sigma in world units."""
    grid = np.zeros((view.height, view.width))
    px = view.to_px(np.asarray(xy, dtype=np.float64)[:, :2]).astype(int)
    w = np.ones(len(px)) if weights is None else np.asarray(weights, dtype=np.float64)
    ok = (px[:, 0] >= 0) & (px[:, 0] < view.width) & (px[:, 1] >= 0) & (px[:, 1] < view.height)
    np.add.at(grid, (px[ok, 1], px[ok, 0]), w[ok])
    sigma = max(1.0, sigma_units / view.units_per_px)
    radius = int(3 * sigma)
    k = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    k /= k.sum()
    # separable blur via FFT-free convolution along each axis
    grid = np.apply_along_axis(lambda r: np.convolve(r, k, mode="same"), 1, grid)
    grid = np.apply_along_axis(lambda c: np.convolve(c, k, mode="same"), 0, grid)
    return grid


def heatmap(base: Image.Image, view: TopDownView, xy: np.ndarray,
            weights: np.ndarray | None = None, sigma_units: float = 64,
            alpha: float = 0.65) -> Image.Image:  # fmt: skip
    """Blend a density heatmap of world points over a top-down image of the same view."""
    d = density(view, xy, weights, sigma_units)
    if d.max() > 0:
        d = d / d.max()
    idx = d * (len(RAMP) - 1)
    lo = np.floor(idx).astype(int).clip(0, len(RAMP) - 2)
    frac = (idx - lo)[..., None]
    rgb = RAMP[lo] * (1 - frac) + RAMP[lo + 1] * frac
    a = (np.clip(d * 3, 0, 1) * alpha)[..., None]  # faint where sparse, opaque where hot
    out = np.asarray(base.convert("RGB"), dtype=np.float64) * (1 - a) + rgb * a
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))
