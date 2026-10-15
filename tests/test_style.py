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


def test_sheets_group_by_zone_six_per_sheet(tmp_path):
    from mapforge.style.sheets import make_sheets

    imgs = []
    for k in range(8):
        name = f"v{k}.png"
        Image.fromarray(np.full((72, 128, 3), 30 * k, dtype=np.uint8)).save(tmp_path / name)
        imgs.append({"file": name, "zone": "a" if k < 7 else "b", "subject": f"s{k}"})
    sheets = make_sheets(tmp_path, imgs, tmp_path / "sheets")
    assert [(s["file"], len(s["tiles"])) for s in sheets] == [("a_1.png", 6), ("a_2.png", 1),
                                                               ("b_1.png", 1)]  # fmt: skip
    assert sheets[0]["tiles"][5] == {"n": 6, "image": "v5.png", "subject": "s5"}
    assert Image.open(tmp_path / "sheets" / "a_1.png").size == (1920, 760)


def test_local_review_writes_notes_progress_and_an_answer(tmp_path, monkeypatch):
    import json

    from mapforge.config import Config, load_config
    from mapforge.style import local

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"))
    cfg = Config(root=base.root, data=data)
    style = tmp_path / "build" / "m" / "style"
    (style / "sheets").mkdir(parents=True)
    (tmp_path / "maps" / "m").mkdir(parents=True)
    (tmp_path / "maps" / "m" / "ART_DIRECTION.md").write_text("art", encoding="utf-8")
    Image.new("RGB", (8, 8)).save(style / "sheets" / "a_1.png")
    sheets = [{"file": "a_1.png", "zone": "a", "tiles": [
        {"n": 1, "image": "x.png", "subject": "a_site"},
        {"n": 2, "image": "y.png", "subject": "A"}]}]  # fmt: skip
    (style / "sheets.json").write_text(json.dumps(sheets), encoding="utf-8")
    reply = {"images": [
        {"n": 1, "zone_match": 2, "flag": "critical", "note": "rust on rust", "fix": "grey floor"},
        {"n": 2, "zone_match": 5, "flag": "ok", "note": "fine", "fix": ""}]}  # fmt: skip
    sent = []

    def fake_post(url, body, timeout):
        sent.append(body)
        return {"choices": [{"message": {"content": json.dumps(reply)}}]}

    monkeypatch.setattr(local, "_post", fake_post)
    published = []
    answer = local.run_local(cfg, "m", lambda: published.append(1))
    assert sent[0]["response_format"]["type"] == "json_schema" and len(published) == 2
    assert answer["findings"] == [{"severity": "critical", "image": "x.png", "where": "a_site",
                                   "what": "rust on rust", "fix": "grey floor"}]  # fmt: skip
    assert answer["zones"] == [{"zone": "a", "score": 4, "reason": "mean of the views"}]
    prog = json.loads((style / "progress.json").read_text(encoding="utf-8"))
    assert prog["state"] == "done" and prog["done"] == 1
    assert len(json.loads((style / "notes.json").read_text(encoding="utf-8"))) == 2


def test_local_review_retries_an_empty_answer_and_resumes(tmp_path, monkeypatch):
    import json

    from mapforge.config import Config, load_config
    from mapforge.style import local

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"))
    cfg = Config(root=base.root, data=data)
    style = tmp_path / "build" / "m" / "style"
    (style / "sheets").mkdir(parents=True)
    (tmp_path / "maps" / "m").mkdir(parents=True)
    (tmp_path / "maps" / "m" / "ART_DIRECTION.md").write_text("art", encoding="utf-8")
    sheets = []
    for name in ("a_1.png", "b_1.png"):
        Image.new("RGB", (8, 8)).save(style / "sheets" / name)
        sheets.append({"file": name, "zone": name[0], "tiles": [
            {"n": 1, "image": f"{name[0]}.png", "subject": name[0]}]})  # fmt: skip
    (style / "sheets.json").write_text(json.dumps(sheets), encoding="utf-8")
    done = [{"image": "a.png", "subject": "a", "zone": "a", "sheet": "a_1.png", "flag": "ok",
             "zone_match": 5, "note": "fine", "fix": "", "source": "local"}]  # fmt: skip
    (style / "notes.json").write_text(json.dumps(done), encoding="utf-8")
    reply = {"images": [{"n": 1, "zone_match": 4, "flag": "ok", "note": "fine", "fix": ""}]}
    budgets = []

    def fake_post(url, body, timeout):
        budgets.append(body["max_tokens"])
        content = "" if len(budgets) == 1 else json.dumps(reply)  # first answer is empty
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(local, "_post", fake_post)
    answer = local.run_local(cfg, "m", resume=True)
    assert budgets == [8000, 12000]  # only sheet b_1 asked, retried with 1.5x the budget
    assert {z["zone"] for z in answer["zones"]} == {"a", "b"}


def test_export_writes_the_web_form(tmp_path):
    import json

    from mapforge.style.publish import block, export

    build = tmp_path / "build"
    (build / "style").mkdir(parents=True)
    (build / "renders").mkdir()
    Image.new("RGB", (1280, 720), (90, 60, 40)).save(build / "style" / "area_a_east.png")
    (build / "style" / "index.json").write_text(json.dumps({"images": []}), encoding="utf-8")
    (build / "style" / "notes.json").write_text("[]", encoding="utf-8")
    Image.new("RGB", (1000, 800)).save(build / "renders" / "topdown_raw.png")
    view = {"world_rect": [-100, -80, 100, 80], "size": [1000, 800], "units_per_px": 0.2}
    base = {"base_for_overlays": {"file": "topdown_raw.png", "view": view}}
    (build / "renders" / "index.json").write_text(json.dumps(base), encoding="utf-8")
    out = export(build, tmp_path / "web")
    assert Image.open(out / "area_a_east_full.jpg").size == (1280, 720)
    assert Image.open(out / "area_a_east.jpg").size == (480, 270)
    mm = json.loads((out / "minimap.json").read_text(encoding="utf-8"))
    assert mm == {"world_rect": [-100, -80, 100, 80], "size": [512, 410]}
    assert (out / "notes.json").is_file() and not (out / "progress.json").exists()
    assert "data-base='img/v001/style/'" in block("img/v001/style/")


def test_a_sheet_that_keeps_failing_is_skipped_not_fatal(tmp_path, monkeypatch):
    import json

    from mapforge.config import Config, load_config
    from mapforge.style import local

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(build_dir=str(tmp_path / "build"), maps_dir=str(tmp_path / "maps"))
    cfg = Config(root=base.root, data=data)
    style = tmp_path / "build" / "m" / "style"
    (style / "sheets").mkdir(parents=True)
    (tmp_path / "maps" / "m").mkdir(parents=True)
    (tmp_path / "maps" / "m" / "ART_DIRECTION.md").write_text("art", encoding="utf-8")
    sheets = []
    for name in ("a_1.png", "b_1.png"):
        Image.new("RGB", (8, 8)).save(style / "sheets" / name)
        sheets.append({"file": name, "zone": name[0], "tiles": [
            {"n": 1, "image": f"{name[0]}.png", "subject": name[0]}]})  # fmt: skip
    (style / "sheets.json").write_text(json.dumps(sheets), encoding="utf-8")
    good = json.dumps({"images": [{"n": 1, "zone_match": 4, "flag": "ok", "note": "", "fix": ""}]})

    def fake_post(url, body, timeout):  # sheet a: cut-off JSON every time; sheet b: fine
        text = body["messages"][0]["content"][0]["text"]
        content = '{"images": [' if "Zone: a" in text else good
        return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setattr(local, "_post", fake_post)
    answer = local.run_local(cfg, "m")
    prog = json.loads((style / "progress.json").read_text(encoding="utf-8"))
    assert prog["state"] == "done" and [s["sheet"] for s in prog["skipped"]] == ["a_1.png"]
    assert "1 sheet(s) skipped: a_1.png" in answer["summary"]


def test_a_recompile_keeps_the_style_review():
    from mapforge.compile.run import KEEP_ON_COMPILE

    assert {"style", "style.json"} <= KEEP_ON_COMPILE
