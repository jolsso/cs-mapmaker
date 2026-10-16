from types import SimpleNamespace

import numpy as np

from mapforge.render import cameras


def test_site_approach_never_falls_back_to_the_t_spawn(monkeypatch):
    # a straight walk of 20 nodes, 100 u apart: T spawn at x=0, the site entry at x=1900;
    # cover hides the site centre from everywhere, but the entry itself is visible
    feet = np.array([[x * 100.0, 0.0, 0.0] for x in range(20)])
    graph = SimpleNamespace(feet=feet, seeds=[0], shortest_path=lambda s, t: list(range(20)))
    monkeypatch.setattr(cameras, "spawn_origins", lambda ents: ([None], ["T"]))
    monkeypatch.setattr(
        cameras, "bomb_sites", lambda bsp: [[(np.r_[2000, -100, 0], np.r_[2400, 100, 64])]]
    )
    monkeypatch.setattr(cameras, "nodes_touching", lambda g, a, b: np.array([19]))
    monkeypatch.setattr(cameras, "best_view", lambda bsp, eye, c: c)
    centre_x = 2200
    monkeypatch.setattr(cameras, "line_of_sight", lambda bsp, eye, t: t[0] != centre_x)
    cam = next(
        c for c in cameras.auto_cameras(SimpleNamespace(entities=[]), graph) if "site" in c.name
    )
    assert 1000 <= cam.eye[0] <= 1700  # on the approach, not at the spawn (x=0)
