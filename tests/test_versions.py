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
