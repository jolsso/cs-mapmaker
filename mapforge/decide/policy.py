"""Check a Decide plan against FITNESS: allowed change types, limits, locked decisions.

The orchestrator applies only `accepted` changes; everything else is reported with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mapforge.config import REPO_ROOT

CONNECTION_TYPES = ("add_connection", "remove_connection")

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "params": {"type": "object"},
                    "rationale": {"type": "string"},
                    "addresses": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["type", "params", "rationale"],
            },
        },
        "expected_effect": {"type": "string"},
        "risk": {"type": "string"},
        "escalate": {"type": "boolean"},
        "structural_needs_human": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"rule": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["rule", "reason"],
            },
        },
        "needs_human": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"annotation": {"type": "string"}, "reason": {"type": "string"}},
                "required": ["annotation", "reason"],
            },
        },
        "escalation_reason": {"type": "string"},
    },
    "required": ["summary", "changes", "expected_effect", "risk", "escalate"],
}


def load_fitness(root: Path = REPO_ROOT) -> dict[str, Any]:
    return yaml.safe_load((root / "config" / "fitness.yaml").read_text(encoding="utf-8"))


LOCKED_MAP = "de_forge01"  # the map the top-level `locked` block was approved for


def locked_for(fitness: dict[str, Any], map_name: str | None) -> dict[str, Any]:
    """The locked decisions of a map: its own entry under `locked_maps`, else `locked` (the
    decisions approved for de_forge01 at Gate A, which earlier maps share)."""
    own = (fitness.get("locked_maps") or {}).get(map_name or "")
    return own if own is not None else fitness.get("locked", {})


@dataclass
class Verdict:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)  # change + "reason"
    errors: list[str] = field(default_factory=list)  # plan-level problems

    @property
    def ok(self) -> bool:
        return not self.errors and not self.rejected

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "accepted": self.accepted, "rejected": self.rejected,
                "errors": self.errors}  # fmt: skip


def _numbers(v: Any) -> list[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [float(v)]
    if isinstance(v, list) and all(isinstance(x, (int, float)) for x in v):
        return [float(x) for x in v]
    raise ValueError(f"not a number or list of numbers: {v!r}")


def _mentions(change: dict[str, Any], names: list[str]) -> str | None:
    text = " ".join(str(v) for v in change.get("params", {}).values()).lower()
    for n in names:
        if n and n.lower() in text:
            return n
    return None


def check_plan(
    plan: Any,
    fitness: dict[str, Any],
    phase: float = 6,
    map_name: str | None = None,
    graph_wishes: set[str] | None = None,
) -> Verdict:
    """Validate structure, then each change against the allowed toolbox and locked decisions.

    `graph_wishes`: "annotation:<id>" of the human's graph-editor changes. A change addressing one
    is the human's own request: the per-iteration limits and the move cap do not apply to it
    (locks, protected elements and minimum widths still do)."""
    v = Verdict()
    if not isinstance(plan, dict):
        v.errors.append("plan must be a JSON object")
        return v
    for key in PLAN_SCHEMA["required"]:
        if key not in plan:
            v.errors.append(f"missing field: {key}")
    if not isinstance(plan.get("changes", []), list):
        v.errors.append("changes must be a list")
        return v
    if plan.get("escalate") and not plan.get("escalation_reason"):
        v.errors.append("escalate is true but escalation_reason is empty")

    allowed = fitness["allowed_changes"]
    locked = locked_for(fitness, map_name)
    frozen = bool(locked.get("geometry_frozen"))
    protected = [*locked.get("landmarks", []), *[str(s) for s in locked.get("site_locations", [])]]
    connections = 0
    per_type: dict[str, int] = {}
    for change in plan.get("changes", []):
        reason = None
        ctype = change.get("type") if isinstance(change, dict) else None
        spec = allowed.get(ctype) if ctype else None
        requested = (
            bool(graph_wishes)
            and isinstance(change, dict)
            and any(str(a) in graph_wishes for a in change.get("addresses", []) or [])
        )
        if spec is None:
            reason = f"type {ctype!r} is not in the allowed toolbox (FITNESS.md)"
        else:
            params = change.get("params", {}) or {}
            missing = [p for p in spec.get("params", []) if p not in params]
            if missing:
                reason = f"missing params {missing}"
            elif frozen and not spec.get("after_gate_b"):
                # Gate B freezes the layout (areas, doors, routes, spawns, levels); cover,
                # props and lighting stay free inside the theme
                reason = "the layout is frozen (after Gate B): only cover/props and lighting"
            elif spec.get("from_phase") and phase < spec["from_phase"]:
                reason = f"{ctype} only from phase {spec['from_phase']}"
            elif spec.get("before_gate_b_only") and frozen:
                reason = f"{ctype} only before Gate B"
            elif spec.get("requires_annotation") and not any(
                str(a).startswith("annotation:") for a in change.get("addresses", []) or []
            ):
                reason = (
                    f"{ctype} only on a human's request (addresses must name an annotation:<id>)"
                )
            else:
                try:
                    if "max_abs_delta" in spec and not requested:
                        key = "delta" if "delta" in params else "length_delta"
                        worst = max(abs(x) for x in _numbers(params[key]))
                        if worst > spec["max_abs_delta"]:
                            reason = f"{key} {worst:g} exceeds ±{spec['max_abs_delta']}"
                    if "min_width" in spec and min(_numbers(params["width"])) < spec["min_width"]:
                        reason = f"width below the {spec['min_width']} unit norm"
                except ValueError as exc:
                    reason = str(exc)
            if reason is None and requested:
                pass  # the human asked for exactly this: no per-iteration limits
            elif reason is None and ctype in CONNECTION_TYPES:
                connections += 1
                if connections > int(spec.get("max_per_iteration", 1)):
                    reason = "only one connection change per iteration"
            elif reason is None and "max_per_iteration" in spec:
                per_type[ctype] = per_type.get(ctype, 0) + 1
                if per_type[ctype] > int(spec["max_per_iteration"]):
                    reason = f"at most {spec['max_per_iteration']} {ctype} per iteration"
            if reason is None and (hit := _mentions(change, protected)):
                reason = f"touches locked decision {hit!r}"
        if reason:
            v.rejected.append({**change, "reason": reason} if isinstance(change, dict)
                              else {"change": change, "reason": reason})  # fmt: skip
        else:
            v.accepted.append(change)
    return v
