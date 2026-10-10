from mapforge.compile.log import parse_compile_log, parse_limits

LEAK_LOG = """\
SolidBSP [hull 0] 12 (0.00 seconds)
Warning: === LEAK in hull 0 ===
Entity info_player_deathmatch at ( 384  128   36)
Error:
  A LEAK is a hole in the map, where the inside of it is exposed to the
[bsp] exit=0 time=0.1s

"""

TABLE = """\
Object names  Objects/Maxobjs  Memory / Maxmem  Fullness
------------  ---------------  ---------------  --------
models              1/512           64/32768    ( 0.2%)
* worldfaces       90/32768          0/0        ( 0.3%)
lightdata        [variable]      43662/50331648 ( 0.1%)
* AllocBlock        2/64             0/0        ( 3.1%)
3 textures referenced
0 wad files required to run the map
"""


def test_leak_is_parsed(tmp_path):
    base = tmp_path / "m"
    base.with_suffix(".lin").write_text("0 528 128 - -540 528 128\n-540 528 128 - -528 -540 128\n")
    report = parse_compile_log(LEAK_LOG, base)
    leak = report["leak"]
    assert leak["hull"] == 0
    assert leak["entity"] == {"classname": "info_player_deathmatch", "origin": [384, 128, 36]}
    assert leak["first_point"] == [0, 528, 128]
    assert leak["line"] == [[0, 528, 128], [-540, 528, 128], [-528, -540, 128]]
    # the empty "Error:" takes its message from the next line; LEAK banner is not a warning
    assert report["errors"] == [
        "A LEAK is a hole in the map, where the inside of it is exposed to the"
    ]
    assert report["warnings"] == []
    assert report["steps"] == [{"step": "bsp", "exit_code": 0, "seconds": 0.1}]


def test_limits_table():
    rows = {r["name"]: r for r in parse_limits(TABLE)}
    assert rows["models"] == {
        "name": "models", "count": 1, "max": 512, "memory": 64, "max_memory": 32768,
        "fullness_pct": 0.2,
    }  # fmt: skip
    assert rows["lightdata"]["count"] is None and rows["lightdata"]["memory"] == 43662
    assert rows["AllocBlock"]["fullness_pct"] == 3.1
    report = parse_compile_log(TABLE, __import__("pathlib").Path("x"))
    assert report["textures_referenced"] == 3 and report["wads_required"] == 0
