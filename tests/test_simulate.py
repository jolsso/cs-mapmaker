from pathlib import Path

import numpy as np

from mapforge.config import load_config
from mapforge.simulate.image import context_files, image_tag
from mapforge.simulate.records import (
    EVENTS,
    POSITIONS,
    ROUNDS,
    load_run,
    site_of,
    valid_round,
)
from mapforge.simulate.server import ServerJob, server_cfg, yapb_cfg
from mapforge.simulate.stats import stop_decision, summarize, wilson

PLUGIN = Path(__file__).resolve().parent.parent / "server" / "plugins" / "mapforge_tracker.sma"


def _write(run: Path, name: str, schema, rows: list[str]) -> None:
    run.mkdir(parents=True, exist_ok=True)
    header = ",".join(n for n, _ in schema)
    (run / name).write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")


def test_plugin_headers_match_the_schema():
    """The tracker plugin writes exactly the columns the loader checks."""
    src = PLUGIN.read_text(encoding="utf-8")
    for name, schema in (("positions", POSITIONS), ("events", EVENTS), ("rounds", ROUNDS)):
        assert f'"{name}.csv", "' + ",".join(n for n, _ in schema) + '"' in src


def test_load_run_types_rows_and_reports_errors(tmp_path):
    run = tmp_path / "s0"
    _write(run, "positions.csv", POSITIONS, ["r,1,0.50,3,T,1,10.0,20.0,36.0,90.0,0.0,100,ak47"])
    _write(
        run,
        "events.csv",
        EVENTS,
        ['r,1,4.00,kill,3,T,5,CT,0,0,0,1,1,1,ak47,"{""headshot"":1,""teamkill"":0}"'],
    )
    _write(
        run, "rounds.csv", ROUNDS, ["r,1,10.0,80.0,T,bomb,A,2,0,0,5,5", "r,2,1,2,X,odd,,0,0,0,5,5"]
    )
    data, errors = load_run(run)
    assert data["positions"][0]["x"] == 10.0 and data["positions"][0]["team"] == "T"
    assert data["events"][0]["extra"] == '{"headshot":1,"teamkill":0}'
    assert len(data["rounds"]) == 1 and len(errors) == 1 and "rounds.csv:3" in errors[0]


def test_valid_round_needs_winner_full_teams_and_no_humans():
    r = {"winner": "CT", "humans_on_team": 0, "t_players": 5, "ct_players": 5}
    assert valid_round(r, 5)
    assert not valid_round({**r, "humans_on_team": 1}, 5)
    assert not valid_round({**r, "winner": ""}, 5)
    assert not valid_round({**r, "t_players": 4}, 5)


def test_site_of_picks_the_nearest_site():
    sites = [
        [(np.array([0, 0, 0]), np.array([100, 100, 64]))],
        [(np.array([1000, 0, 0]), np.array([1100, 100, 64]))],
    ]
    assert site_of(np.array([50, 50, 10]), sites, ["A", "B"]) == "A"
    assert site_of(np.array([1300, 50, 10]), sites, ["A", "B"]) == "B"


def test_wilson_interval():
    lo, hi = wilson(50, 100)
    assert 0.40 < lo < 0.41 and 0.59 < hi < 0.60
    assert wilson(0, 0) == (0.0, 1.0)


def _rounds(t_wins: int, n: int, plants_a: int = 0, plants_b: int = 0) -> list[dict]:
    sites = ["A"] * plants_a + ["B"] * plants_b
    return [
        {"winner": "T" if i < t_wins else "CT", "plant_site": sites[i] if i < len(sites) else ""}
        for i in range(n)
    ]


def test_early_stop_only_for_results_decided_outside():
    targets = {"t_winrate": [0.45, 0.55], "site_split_a": [0.35, 0.65]}
    lopsided = summarize(_rounds(2, 20, 5, 5), 0.95, targets)  # T wins 10 %
    assert stop_decision(lopsided, 100, 100) == (True, "t_winrate decided outside the target range")
    even = summarize(_rounds(10, 20, 5, 5), 0.95, targets)
    assert stop_decision(even, 100, 100) == (False, "")  # inside, but needs min_rounds
    assert stop_decision(summarize(_rounds(50, 100, 25, 25), 0.95, targets), 100, 200)[0] is False
    assert stop_decision(even, 100, 20) == (True, "max_rounds (20) reached")


def test_server_cfg_sets_run_cvars_and_bot_quota(tmp_path):
    sim = load_config().data["simulate"]
    job = ServerJob(map_name="de_x", run_id="b01s0", rounds=10, out_dir=tmp_path, timescale=4)
    text = server_cfg(sim, job)
    assert 'mf_run_id "b01s0"' in text and "mf_max_rounds 10" in text
    assert "sys_timescale 4" in text and "mp_roundtime 2.5" in text
    yb = yapb_cfg(sim)
    assert f"yb_quota {2 * sim['bots_per_team']}" in yb and 'yb_graph_url ""' in yb


def test_image_tag_follows_the_build_context():
    cfg = load_config()
    files = context_files(cfg)
    assert "plugins/mapforge_tracker.sma" in files and "Dockerfile" in files
    assert all(b"\r\n" not in v for v in files.values())
    changed = {
        **files,
        "plugins/mapforge_tracker.sma": files["plugins/mapforge_tracker.sma"] + b"//",
    }
    assert image_tag(cfg, files) == image_tag(cfg, dict(files))
    assert image_tag(cfg, files) != image_tag(cfg, changed)
