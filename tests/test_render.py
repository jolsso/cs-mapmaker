import json

import numpy as np
import pytest
from conftest import needs_compilers
from PIL import Image

from mapforge.compile.run import compile_map
from mapforge.config import load_config
from mapforge.wad.dev_textures import main as make_dev_wad


def _gl_available() -> bool:
    try:
        from mapforge.render.gl import create_context

        create_context().release()
    except Exception:
        return False
    return True


pytestmark = [
    pytest.mark.slow,
    needs_compilers,
    pytest.mark.skipif(not _gl_available(), reason="no OpenGL context (EGL/Mesa)"),
]


@pytest.fixture(scope="module")
def rendered():
    from mapforge.render.run import render_map

    cfg = load_config()
    make_dev_wad()
    bsp = compile_map(cfg, "test_box")
    index = render_map(cfg, "test_box", bsp)
    return cfg.path("build_dir") / "test_box" / "renders", index


def test_index_lists_images_and_finds_all_textures(rendered):
    out, index = rendered
    files = [i["file"] for i in index["images"]]
    assert files[:2] == ["topdown.png", "topdown_light.png"]
    # test_box has no bomb sites: only the two spawn cameras
    assert files[2:] == ["cam_spawn_t.png", "cam_spawn_ct.png"]
    assert all((out / f).is_file() for f in files)
    assert index["missing_textures"] == []
    assert json.loads((out / "index.json").read_text())["map"] == "test_box"


def test_topdown_shows_the_lit_floor(rendered):
    out, index = rendered
    img = np.asarray(Image.open(out / "topdown_raw.png"))
    view = index["base_for_overlays"]["view"]
    assert list(img.shape[1::-1]) == view["size"]
    # The room centre is lit floor (DEV_FLOOR grey * light), not the background.
    centre = img[img.shape[0] // 2 - 40, img.shape[1] // 2 - 40].astype(int)
    assert centre.min() > 60 and abs(centre[0] - centre[2]) < 40
    # Outside the room (corner of the image) is background.
    assert img[2, 2].max() < 30


def test_spawn_camera_sees_the_room(rendered):
    out, _ = rendered
    img = np.asarray(Image.open(out / "cam_spawn_t.png")).astype(int)
    sky = np.array([0.55, 0.62, 0.72]) * 255
    # A closed room: no pixel should show the sky background colour.
    assert np.abs(img - sky).sum(axis=2).min() > 20
