"""mapforge.wad.catalog: which WADs a map references; the game's WADs are never embedded."""

import numpy as np
import pytest

from mapforge.config import load_config
from mapforge.wad.catalog import catalog, contact_sheet, texture_index, wads_for
from mapforge.wad.wad3 import Texture, write_wad3


def _wad(path, *names, colour=7):
    pal = np.zeros((256, 3), dtype=np.uint8)
    pal[colour] = (200, 100, 50)
    write_wad3(path, [Texture(n, np.full((16, 32), colour, dtype=np.uint8), pal) for n in names])
    return path


def test_wads_for_picks_the_providing_wads_in_search_order(tmp_path):
    own, game = tmp_path / "own", tmp_path / "game"
    own.mkdir()
    game.mkdir()
    _wad(own / "mine.wad", "DEV_FLOOR", "RUST")
    _wad(game / "cs_bdog.wad", "RUST", "TRAIN_SIDE")  # RUST is shadowed by our own
    _wad(game / "decals.wad", "BOMBSITE_A")
    wads, missing = wads_for(["dev_floor", "TRAIN_SIDE", "rust", "CLIP", "NOPE"],
                             [own, game, tmp_path / "absent"])  # fmt: skip
    assert wads == ["mine.wad", "cs_bdog.wad"] and missing == ["NOPE"]
    assert texture_index([own, game])["RUST"] == "mine.wad"
    cat = catalog([game])
    assert cat["cs_bdog.wad"][0] == {"name": "RUST", "size": [32, 16], "rgb": [200, 100, 50]}
    assert contact_sheet(game / "cs_bdog.wad", tmp_path / "sheet.png") == 2
    assert (tmp_path / "sheet.png").is_file()


def test_only_our_own_wads_are_embedded():
    cfg = load_config()
    own = {p.name for p in cfg.wad_dirs[0].glob("*.wad")}
    include = cfg.data["wad"]["include"]
    assert include and set(include) <= own, "wad.include may only name WADs from assets/wads"


def test_game_wads_are_searched_after_our_own():
    dirs = [str(d) for d in load_config().data["paths"]["wad_dirs"]]
    assert dirs[0] == "assets/wads" and any(d.startswith("/refmaps/hl/") for d in dirs[1:])


@pytest.mark.skipif(not __import__("pathlib").Path("/refmaps/hl/cstrike/cstrike.wad").is_file(),
                    reason="needs the Half-Life install mounted at /refmaps/hl")  # fmt: skip
def test_a_standard_texture_resolves_to_a_game_wad():
    cfg = load_config()
    name = next(iter(texture_index([cfg.wad_dirs[1]])))  # any texture in cstrike/*.wad
    wads, missing = wads_for([name, "DEV_FLOOR"], cfg.wad_dirs)
    assert not missing and wads[0] == "mapforge_dev.wad" and len(wads) == 2


@pytest.mark.slow
@pytest.mark.skipif(not __import__("pathlib").Path("/refmaps/hl/cstrike/tswad.wad").is_file(),
                    reason="needs the Half-Life install mounted at /refmaps/hl")  # fmt: skip
def test_a_map_with_game_textures_compiles_and_references_the_wad(tmp_path):
    import copy

    from conftest import needs_compilers  # noqa: F401  (compilers are baked into the image)
    from test_generator_features import FEAT

    from mapforge.bsp.reader import read_bsp
    from mapforge.compile.run import compile_map
    from mapforge.config import Config
    from mapforge.generator.build import generate
    from mapforge.generator.run import assign_wads
    from mapforge.generator.spec import parse_layout
    from mapforge.mapfile.writer import write_map
    from mapforge.wad.dev_textures import main as make_dev_wad

    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"), build_dir=str(tmp_path / "build"))
    cfg = Config(root=base.root, data=data)
    lay = copy.deepcopy(FEAT)
    lay["zones"]["a"].update(floor="TSFLRGRT", wall="TSHULL1")  # oil rig textures (tswad.wad)
    g = generate(parse_layout(lay))
    assert assign_wads(g.mapfile, cfg) == []
    assert g.mapfile.worldspawn.properties["wad"] == "mapforge_dev.wad;tswad.wad"
    write_map(g.mapfile, tmp_path / "maps" / "de_gen_feat" / "src" / "de_gen_feat.map")
    make_dev_wad()
    bsp = read_bsp(compile_map(cfg, "de_gen_feat"))
    tex = {t.name.upper(): t for t in bsp.textures}
    assert not tex["TSFLRGRT"].embedded  # referenced from the game's WAD, not distributed
    assert tex["DEV_FLOOR"].embedded
    assert "tswad.wad" in bsp.entities[0]["wad"]
