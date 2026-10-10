import xml.etree.ElementTree as ET

from mapforge.site import charts


def _ok(svg: str) -> None:
    root = ET.fromstring(svg)
    assert (
        root.tag.endswith("svg")
        and root.find("{*}title") is not None
        or root.find("title") is not None
    )


def test_all_charts_are_valid_svg():
    _ok(charts.bullet("T-winrate", 46, [45, 55], [33, 60], 0, 100, "%", 0))
    _ok(charts.bullet("Døde zoner", None, [0, 5]))
    _ok(charts.running_rate([True, False, True], [0.45, 0.55], "T"))
    _ok(charts.stacked([("T <bombe>", 3, "t"), ("CT & tid", 0, "ct")], "udfald"))
    _ok(charts.histogram([30.0, 60.0, 61.0, 90.0], 5, [50, 100], "længde"))
    row = {"site": "A", "T": {"median_s": 16}, "CT": {"median_s": 4}, "ct_lead_s": 12}
    _ok(charts.timings([row], (14, 26), 3))
    _ok(charts.limits([{"name": "planes", "pct": 1.2}, {"name": "x", "pct": 95}], 75, 90))
    _ok(charts.trend([("001", 0.4), ("002", None), ("003", 0.3)], "score"))
    _ok(charts.ring(0.86, "fremdrift"))


def test_empty_inputs_give_no_chart():
    assert charts.running_rate([], None, "x") == ""
    assert charts.histogram([], 5, None, "x") == ""
    assert charts.timings([{"site": "A"}], (14, 26), 3) == ""
    assert charts.trend([("001", 1.0)], "x") == ""
