"""Style review (phase 7): numbers per image, deterministic findings, answer schema, cameras."""

import copy

import numpy as np
import pytest
from PIL import Image

from mapforge.style.run import check_answer, deterministic_findings, image_numbers


def test_image_numbers_spot_burnt_out_and_black(tmp_path):
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    img[:5] = 255  # top half white
    Image.fromarray(img).save(tmp_path / "x.png")
    n = image_numbers(tmp_path / "x.png")
    assert n["burnt"] == 0.5 and n["black"] == 0.5 and n["mean_luma"] == 127.5


def test_deterministic_findings_and_pass_rule_inputs():
    index = {"missing_textures": ["NOPE"], "dark_zones": 2,
             "images": [{"file": "a.png", "subject": "a_site", "burnt": 0.4},
                        {"file": "b.png", "subject": "b_site", "burnt": 0.1}]}  # fmt: skip
    f = deterministic_findings(index)
    assert [x["severity"] for x in f] == ["critical", "critical", "medium"]
    assert f[2]["image"] == "a.png"


def test_check_answer_schema():
    good = {"summary": "s", "zones": [{"zone": "a", "score": 4, "reason": "r"}],
            "findings": [{"severity": "medium", "image": "x.png", "where": "A", "what": "w",
                          "fix": "f"}]}  # fmt: skip
    assert check_answer(good) is good
    bad = copy.deepcopy(good)
    bad["findings"][0]["severity"] = "major"
    with pytest.raises(RuntimeError, match="severity"):
        check_answer(bad)
    bad = copy.deepcopy(good)
    del bad["findings"][0]["fix"]
    with pytest.raises(RuntimeError, match="fix"):
        check_answer(bad)


@pytest.mark.slow
def test_style_cameras_cover_areas_doors_and_landmarks(tmp_path):
    from conftest import needs_compilers  # noqa: F401
    from test_generator_features import FEAT

    from mapforge.bsp.reader import read_bsp
    from mapforge.compile.run import compile_map
    from mapforge.config import Config, load_config
    from mapforge.generator.build import generate
    from mapforge.generator.spec import parse_layout
    from mapforge.mapfile.writer import write_map
    from mapforge.style.cameras import style_cameras
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data)
    raw = copy.deepcopy(FEAT)
    raw["cover"] = [{"name": "stack", "area": "a_site", "pos": [256, 400], "preset": "crate_stack"}]
    raw["landmarks"] = [{"name": "Stablen", "element": "stack"}]
    raw["chokes"] = [{"name": "Mid-døren", "door": "mid_a"}]
    lay = parse_layout(copy.deepcopy(raw))
    write_map(generate(lay).mapfile, tmp_path / "maps" / "de_gen_feat" / "src" / "de_gen_feat.map")
    make_dev_wad()
    bsp = read_bsp(compile_map(cfg, "de_gen_feat"))
    cams = style_cameras(lay, raw, bsp)
    kinds = {c.kind for c in cams}
    assert kinds == {"area", "door", "landmark"}
    assert {c.area for c in cams if c.kind == "area"} == set(lay.areas)
    assert any(c.subject == "mid_a" for c in cams if c.kind == "door")  # choke + site entrance
    for c in cams:  # every eye is in open air
        assert bsp.point_contents(np.array([c.cam.eye]))[0] != -2
