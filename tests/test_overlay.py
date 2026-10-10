import numpy as np
from PIL import Image

from mapforge.render.overlay import density, heatmap
from mapforge.render.topdown import TopDownView

VIEW = TopDownView(x0=0, y0=0, x1=1000, y1=500, width=200, height=100)


def test_to_px_is_north_up():
    px = VIEW.to_px(np.array([[0, 500], [1000, 0], [500, 250]]))
    assert px.tolist() == [[0, 0], [200, 100], [100, 50]]


def test_density_peaks_at_the_points():
    d = density(VIEW, np.array([[250, 250], [250, 250], [750, 250]]), sigma_units=40)
    assert np.unravel_index(d.argmax(), d.shape) == (50, 50)  # the doubled point wins
    assert d[50, 150] > d[50, 100]  # the single point is a local peak too
    assert np.isclose(d.sum(), 3, rtol=0.02)  # mass is preserved by the blur


def test_heatmap_keeps_size_and_leaves_empty_areas_alone():
    base = Image.new("RGB", (200, 100), (40, 40, 40))
    out = heatmap(base, VIEW, np.array([[250, 250]]), sigma_units=40)
    assert out.size == base.size
    arr = np.asarray(out)
    assert arr[50, 50].tolist() != [40, 40, 40]
    assert arr[5, 195].tolist() == [40, 40, 40]
