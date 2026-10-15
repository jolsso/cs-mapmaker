"""In-game feedback: the plugin's JSON lines become the map's wishes, once each."""

import copy
import json

from mapforge.config import Config, load_config
from mapforge.feedback import merge, notes_from


def test_notes_become_point_wishes_at_the_aimed_spot_once(tmp_path):
    base = load_config()
    data = copy.deepcopy(base.data)
    data["paths"].update(maps_dir=str(tmp_path / "maps"))
    cfg = Config(root=base.root, data=data)
    (tmp_path / "maps" / "m").mkdir(parents=True)
    lines = [
        {"time": "2026-10-15 16:30:01", "map": "m", "player": "jonas", "category": "light",
         "text": 'too dark "here"', "eye": [10, 20, 64], "aim": [400, 500, 32],
         "origin": [10, 20, 0]},
        {"time": "2026-10-15 16:31:00", "map": "m", "player": "jonas", "category": "",
         "text": "nice crane", "eye": [0, 0, 64], "aim": [-100, 50, 200], "origin": [0, 0, 0]},
    ]  # fmt: skip
    f = tmp_path / "feedback_m.jsonl"
    f.write_text("\n".join(json.dumps(x) for x in lines) + "\n{broken\n", encoding="utf-8")
    notes = notes_from(f)
    assert len(notes) == 2
    new = merge(cfg, "m", notes)
    assert [w["text"] for w in new] == ['[light] too dark "here" (in game)', "nice crane (in game)"]
    assert new[0]["points"] == [[400, 500]] and new[0]["ingame"]["eye"] == [10, 20, 64]
    assert merge(cfg, "m", notes) == []  # collecting again adds nothing
    stored = json.loads((tmp_path / "maps" / "m" / "annotations.json").read_text(encoding="utf-8"))
    assert len(stored) == 2 and stored[0]["ingame"]["category"] == "light"
