from pathlib import Path

from mapforge.site.versions import Version, wish_version


def _v(key: str, created: str) -> Version:
    return Version(key, [Path(".")], {"created": created}, False)


def test_wish_belongs_to_the_version_it_was_drawn_on():
    vers = [
        _v("003", "2026-10-10 17:19"),
        _v("004", "2026-10-10 17:22"),
        _v("005", "2026-10-10 21:55"),
    ]
    assert wish_version({"created": "2026-10-10 21:27"}, vers) == "004"
    assert wish_version({"created": "2026-10-10 21:55"}, vers) == "005"
    assert wish_version({"created": "2026-10-09 10:00"}, vers) == "003"
    assert wish_version({"created": "2026-10-10 23:00", "version": "004"}, vers) == "004"


def test_version_graph_marks_branches_and_dead_ends():
    from pathlib import Path

    from mapforge.site.versions import Version, version_graph

    def v(key, parent, current=False):
        ver = Version(key, [Path(".")], {}, current)
        ver.parent = parent
        return ver

    # 1 <- 2 <- 3, then 4 and 5 built on 3 (dead ends) and 6 built on 3 again (current)
    vers = [v("001", None), v("002", 0), v("003", 1), v("004", 2), v("005", 2), v("006", 2, True)]
    cells, width = version_graph(vers)
    assert "gd fork" in cells[2] and "gd dead" in cells[3] and "gd dead" in cells[4]
    assert "gd cur" in cells[5] and "gd dead" not in cells[1]
    assert cells[2].count("class='gh'") == 2  # two branches leave version 003 sideways
    assert width >= 3 * 16  # three lanes
