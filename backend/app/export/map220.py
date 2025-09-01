from pathlib import Path
from typing import Iterable


def write_empty_map(map_path: Path, wads: Iterable[str] | None = None) -> None:
    """Write a minimal Valve 220 .map with only worldspawn.

    This yields a valid, empty map Hammer can open. Solids will be added by the
    generation pipeline later.
    """
    map_path = Path(map_path)
    map_path.parent.mkdir(parents=True, exist_ok=True)
    wad_value = ";".join(wads or [])

    content = (
        'worldspawn\n'
        '{\n'
        '"mapversion" "220"\n'
        '"classname" "worldspawn"\n'
        + (f'"wad" "{wad_value}"\n' if wad_value else "")
        + '}\n'
    )
    map_path.write_text(content, encoding="utf-8")

