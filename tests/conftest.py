import copy
from pathlib import Path

import pytest

from mapforge.compile.run import CompileError, tool_paths
from mapforge.config import Config, load_config

FIXTURE_MAPS = Path(__file__).parent / "fixtures" / "maps"


def compilers_present() -> bool:
    try:
        tool_paths(load_config())
    except CompileError:
        return False
    return True


needs_compilers = pytest.mark.skipif(not compilers_present(), reason="compilers not fetched")


@pytest.fixture
def fixture_cfg(tmp_path) -> Config:
    """Repo config with maps from tests/fixtures/maps and a throwaway build dir."""
    cfg = load_config()
    data = copy.deepcopy(cfg.data)
    data["paths"]["maps_dir"] = str(FIXTURE_MAPS)
    data["paths"]["build_dir"] = str(tmp_path / "build")
    return Config(root=cfg.root, data=data)
