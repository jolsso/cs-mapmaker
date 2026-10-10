"""Parser for Valve 220 .map files (Half-Life).

Face line: ( x y z ) ( x y z ) ( x y z ) TEXNAME [ ux uy uz uoff ] [ vx vy vz voff ] rot sx sy
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

Vec3 = tuple[float, float, float]

_TOKEN = re.compile(r'"([^"]*)"|(//[^\n]*)|([{}()\[\]])|([^\s{}()\[\]"]+)')


class MapParseError(ValueError):
    def __init__(self, message: str, line: int) -> None:
        super().__init__(f"line {line}: {message}")
        self.line = line


@dataclass(frozen=True)
class Face:
    points: tuple[Vec3, Vec3, Vec3]
    texture: str
    u_axis: tuple[float, float, float, float]
    v_axis: tuple[float, float, float, float]
    rotation: float
    scale: tuple[float, float]
    line: int


@dataclass
class Brush:
    faces: list[Face]
    line: int
    entity_index: int
    brush_index: int


@dataclass
class Entity:
    properties: dict[str, str]
    brushes: list[Brush] = field(default_factory=list)
    line: int = 0

    @property
    def classname(self) -> str:
        return self.properties.get("classname", "")

    @property
    def origin(self) -> Vec3 | None:
        raw = self.properties.get("origin")
        if raw is None:
            return None
        x, y, z = (float(v) for v in raw.split())
        return (x, y, z)


@dataclass
class MapFile:
    entities: list[Entity]

    @property
    def worldspawn(self) -> Entity:
        return self.entities[0]

    def brushes(self) -> list[Brush]:
        return [b for e in self.entities for b in e.brushes]


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    """Return (kind, value, line) tokens; kind is 'str', 'sym' or 'word'. Comments are dropped."""
    tokens = []
    line = 1
    pos = 0
    for m in _TOKEN.finditer(text):
        line += text.count("\n", pos, m.start())
        pos = m.start()
        quoted, comment, sym, word = m.groups()
        if comment is not None:
            continue
        if quoted is not None:
            tokens.append(("str", quoted, line))
        elif sym is not None:
            tokens.append(("sym", sym, line))
        else:
            tokens.append(("word", word, line))
    return tokens


class _Reader:
    def __init__(self, tokens: list[tuple[str, str, int]]) -> None:
        self.tokens = tokens
        self.i = 0

    def peek(self) -> tuple[str, str, int] | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def next(self) -> tuple[str, str, int]:
        tok = self.peek()
        if tok is None:
            last = self.tokens[-1][2] if self.tokens else 1
            raise MapParseError("unexpected end of file", last)
        self.i += 1
        return tok

    def expect(self, sym: str) -> int:
        kind, value, line = self.next()
        if kind != "sym" or value != sym:
            raise MapParseError(f"expected {sym!r}, got {value!r}", line)
        return line

    def number(self) -> float:
        kind, value, line = self.next()
        try:
            return float(value)
        except ValueError:
            raise MapParseError(f"expected number, got {value!r}", line) from None


def _parse_face(r: _Reader) -> Face:
    points = []
    first_line = r.peek()[2]  # type: ignore[index]
    for _ in range(3):
        r.expect("(")
        points.append((r.number(), r.number(), r.number()))
        r.expect(")")
    kind, texture, line = r.next()
    if kind == "sym":
        raise MapParseError(f"expected texture name, got {texture!r}", line)
    axes = []
    for _ in range(2):
        tok = r.peek()
        if tok is None or tok[1] != "[":
            raise MapParseError("not Valve 220 format (missing [ u v ] texture axes)", line)
        r.expect("[")
        axes.append((r.number(), r.number(), r.number(), r.number()))
        r.expect("]")
    rotation = r.number()
    scale = (r.number(), r.number())
    return Face(
        points=(points[0], points[1], points[2]),
        texture=texture,
        u_axis=axes[0],
        v_axis=axes[1],
        rotation=rotation,
        scale=scale,
        line=first_line,
    )


def parse_map(text: str) -> MapFile:
    r = _Reader(_tokenize(text))
    entities: list[Entity] = []
    while r.peek() is not None:
        ent_line = r.expect("{")
        entity = Entity(properties={}, line=ent_line)
        while True:
            kind, value, line = r.next()
            if kind == "sym" and value == "}":
                break
            if kind == "str":
                k2, v2, l2 = r.next()
                if k2 != "str":
                    raise MapParseError(f"expected value for key {value!r}", l2)
                entity.properties[value] = v2
            elif kind == "sym" and value == "{":
                faces = []
                while (tok := r.peek()) is not None and tok[1] != "}":
                    faces.append(_parse_face(r))
                r.expect("}")
                entity.brushes.append(
                    Brush(
                        faces=faces,
                        line=line,
                        entity_index=len(entities),
                        brush_index=len(entity.brushes),
                    )
                )
            else:
                raise MapParseError(f"unexpected token {value!r} in entity", line)
        entities.append(entity)
    if not entities or entities[0].classname != "worldspawn":
        raise MapParseError("first entity must be worldspawn", 1)
    return MapFile(entities=entities)


def read_map(path: Path) -> MapFile:
    return parse_map(path.read_text(encoding="utf-8"))
