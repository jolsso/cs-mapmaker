"""Autonomous loop (phase 6): generate -> validate -> render -> review -> simulate -> analyze ->
decide -> apply, iteration after iteration, within budget and stop criteria (docs/FITNESS.md).

A state machine in runs/<map>/loop.json. Deterministic steps run here; the two judgement steps
(Review, Decide) are answered by the Claude Code session (a fresh subagent per prompt, CLAUDE.md
-> "Review og Decide i sessionen"). When an answer is needed the loop writes the prompt, prints
where the answer goes and exits with code 3; running it again picks up the answer and goes on.

Two speeds: an iteration that fails validation or review goes straight to Decide (seconds to
minutes); only a map that passes review is simulated. Rollback: if a measurement is worse than
the best one beyond the noise (analysis delta), the next plan is applied to the best layout.

Usage:
  python -m mapforge.loop.run --map de_x --init [--force-sim]   # start (iteration 001)
  python -m mapforge.loop.run --map de_x                       # continue until done/awaiting
  python -m mapforge.loop.run --map de_x --status
Exit: 0 = stopped (see stop_reason), 3 = awaiting an answer, 1 = error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from mapforge.config import Config, load_config
from mapforge.decide.policy import load_fitness
from mapforge.runs import iterations, runs_root

AWAIT = 3


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def docker_problem() -> str | None:
    """Why the simulations cannot start (the loop drives HLDS containers through the Docker
    socket), or None. Checked when the loop starts, not an hour later at the first sim step."""
    try:
        import docker

        docker.from_env(timeout=10).ping()
    except Exception as exc:  # docker.errors.DockerException, connection errors, missing socket
        return (
            "Docker svarer ikke (simuleringerne kører i HLDS-containere): start Docker Desktop, "
            f"og kør loopet igen ({type(exc).__name__}: {exc})"
        )
    return None


def _rel(cfg: Config, p: Path) -> str:
    try:
        return p.resolve().relative_to(cfg.root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


class Loop:
    def __init__(self, cfg: Config, map_name: str):
        self.cfg, self.map = cfg, map_name
        self.root = runs_root(cfg, map_name)
        self.state_file = self.root / "loop.json"
        self.build = cfg.path("build_dir") / map_name
        self.layout = cfg.path("maps_dir") / map_name / "layout.yaml"
        self.fitness = load_fitness(cfg.root)
        self.state: dict[str, Any] = _load(self.state_file) or {}

    # ---------------------------------------------------------------- state
    def save(self) -> None:
        # the budget counts the loop's own run time, not the time it stood still (awaiting an
        # answer, cut off and resumed days later): add the time since the last save in this run
        now = time.time()
        if getattr(self, "_mark", None) is not None:
            self.state["active_s"] = round(self.state.get("active_s", 0.0) + now - self._mark, 1)
        self._mark = now
        self.root.mkdir(parents=True, exist_ok=True)
        self.state["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state_file.write_text(
            json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (self.root / "LOOP.md").write_text(self.report(), encoding="utf-8")
        # the website is static: rebuild it when the loop moves on, so "we are here" is current
        # while a long step (simulate) runs, not only when the command exits
        where = (self.state.get("iteration"), self.state.get("step"), self.state.get("status"))
        if where != getattr(self, "_shown", None):
            self._shown = where
            from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

            refresh_site(self.cfg)

    def log(self, msg: str) -> None:
        print(f"[loop {self.map} {self.state.get('iteration', '-')}] {msg}", flush=True)

    @property
    def it_dir(self) -> Path:
        return self.root / self.state["iteration"]

    def _closed(self) -> bool:
        from mapforge import project

        return project.is_closed(self.cfg.path("maps_dir"), self.map)

    def init(self, force_sim: bool) -> None:
        if self._closed():
            raise RuntimeError(f"{self.map} er afsluttet: genåbn den under Input på map-siden")
        if not self.layout.is_file():
            raise RuntimeError(f"{self.layout} missing: the loop changes a layout spec")
        n = (
            int(iterations(self.cfg, self.map)[-1].name) + 1
            if iterations(self.cfg, self.map)
            else 1
        )
        self.state = {
            "map": self.map, "status": "running", "stop_reason": None,
            "started": time.strftime("%Y-%m-%d %H:%M:%S"), "started_ts": time.time(),
            "first_iteration": f"{n:03d}", "iteration": f"{n:03d}", "step": "build",
            "force_sim": force_sim, "rollback": False,
            "counters": {"hard_fail": 0, "review_fail": 0, "since_best": 0, "targets_met": 0, "measured": 0},
            "best": None, "history": [],
        }  # fmt: skip
        self.it_dir.mkdir(parents=True, exist_ok=False)
        self.save()

    def record(self, **kw: Any) -> None:
        hist = self.state["history"]
        if not hist or hist[-1]["iteration"] != self.state["iteration"]:
            hist.append({"iteration": self.state["iteration"]})
        hist[-1].update(kw)

    def check_skip(self) -> bool:
        """The human asked to skip this iteration (map page; maps/<map>/skip.json): from build,
        review or sim go straight to decide. True when it did."""
        from mapforge import skip

        req = skip.pending(self.cfg.path("maps_dir"), self.map)
        if not req or self.state.get("step") not in ("build", "review", "sim"):
            return False
        self.skip_now(self.state["step"], req)
        return True

    def skip_now(self, at: str, req: dict[str, Any] | None) -> None:
        """Record the skip, clear the flag and go to decide (best/rollback untouched)."""
        from mapforge import skip

        reason = (req or {}).get("reason", "")
        self.record(skipped=True, at=at, reason=reason)
        self.state.update(step="decide", skipped=self.state["iteration"])
        self.state.pop("awaiting", None)
        notes = self.it_dir / "NOTES.md"
        notes.parent.mkdir(parents=True, exist_ok=True)
        with notes.open("a", encoding="utf-8") as f:
            f.write(f"\n**Iteration skipped by the human at {at}**"
                    f"{': ' + reason if reason else ''} ({(req or {}).get('time', '')}).\n")  # fmt: skip
        skip.clear(self.cfg.path("maps_dir"), self.map)
        self.log(f"skipped by the human at {at}")
        self.save()

    def stop(self, reason: str) -> int:
        self.state.update(status="stopped", stop_reason=reason, step="done")
        self.state.pop("awaiting", None)
        self.save()
        self.log(f"STOP: {reason} (summary: {_rel(self.cfg, self.root / 'LOOP.md')})")
        return 0

    # ---------------------------------------------------------------- steps
    def step_build(self) -> str:
        from mapforge.generator.run import main as generate
        from mapforge.render.run import main as render
        from mapforge.review.run import review_map
        from mapforge.validate.run import main as validate

        d = self.it_dir
        shutil.copy2(self.layout, d / "layout.yaml")
        t0 = time.time()
        if generate(["--map", self.map]) != 0:
            return self._hard_fail("generate", "layout does not generate")
        src = self.layout.parent / "src" / f"{self.map}.map"
        shutil.copy2(src, d / src.name)
        prev = self._previous(src.name)
        if prev:
            import difflib

            diff = difflib.unified_diff(prev.read_text(encoding="utf-8").splitlines(True),
                                        src.read_text(encoding="utf-8").splitlines(True),
                                        fromfile=f"previous/{src.name}", tofile=f"current/{src.name}")  # fmt: skip
            (d / "map.diff").write_text("".join(diff), encoding="utf-8")
        ok = validate(["--map", self.map]) == 0
        for name in ("compile.json", "compile.log", "validation.json"):
            if (self.build / name).is_file():
                shutil.copy2(self.build / name, d / name)
        if not ok:
            return self._hard_fail("validate", "validation errors (hard requirements)")
        self.state["counters"]["hard_fail"] = 0
        render(["--map", self.map])
        (self.build / "review_answer.json").unlink(missing_ok=True)  # never reuse an old answer
        review_map(self.cfg, self.map, "emit")
        self.record(reached="review", build_s=round(time.time() - t0, 1))
        self.state["step"] = "review"
        self.save()
        return "review"

    def _previous(self, name: str) -> Path | None:
        prev = [
            p / name for p in iterations(self.cfg, self.map) if p.name < self.state["iteration"]
        ]
        prev = [p for p in prev if p.is_file()]
        return prev[-1] if prev else None

    def _reusable_review(self) -> Path | None:
        """The review answer of the newest earlier iteration with a byte-identical .map, if that
        review passed (a failed one is never reused: the plan changed nothing it asked for)."""
        name = f"{self.map}.map"
        cur = self.it_dir / name
        if not cur.is_file():
            return None
        data = cur.read_bytes()
        for p in reversed(iterations(self.cfg, self.map)):
            if p.name >= self.state["iteration"]:
                continue
            ans, rev = p / "review_answer.json", p / "review.json"
            if not ((p / name).is_file() and ans.is_file() and rev.is_file()):
                continue
            passed = json.loads(rev.read_text(encoding="utf-8")).get("passed")
            if passed and (p / name).read_bytes() == data:
                return ans
        return None

    def _hard_fail(self, reached: str, why: str) -> str:
        self.state["counters"]["hard_fail"] += 1
        self.record(reached=reached, why=why)
        self.log(f"hard fail at {reached}: {why}")
        self.state["step"] = "decide"
        self.save()
        return "decide"

    def step_review(self) -> str | int:
        from mapforge.history import snapshot
        from mapforge.review.run import review_map

        answer = self.build / "review_answer.json"
        if not answer.is_file() and (reused := self._reusable_review()):
            # same .map as a reviewed iteration (e.g. a confirmation measurement): same verdict
            shutil.copy2(reused, answer)
            self.log(f"review reused from {reused.parent.name} (identical .map)")
        if not answer.is_file():
            return self._await("review", self.build / "review_prompt.md", answer)
        r = review_map(self.cfg, self.map, "answer")
        snapshot(self.cfg, self.map, note=f"loop iteration {self.state['iteration']}")
        d = self.it_dir
        shutil.copy2(answer, d / "review_answer.json")
        shutil.copy2(self.build / "review.json", d / "review.json")
        if (self.build / "renders").is_dir():
            if (d / "renders").exists():
                shutil.rmtree(d / "renders")
            shutil.copytree(
                self.build / "renders",
                d / "renders",
                ignore=shutil.ignore_patterns("topdown_raw.png"),
            )
        c = self.state["counters"]
        if r["passed"]:
            c["review_fail"] = 0
            self.record(review="pass")
            self.state["step"] = "sim"
        else:
            c["review_fail"] += 1
            self.record(review="fail", reached="review", why=r["summary"][:200])
            self.state["step"] = "sim" if self.state.get("force_sim") else "decide"
        self.save()
        return self.state["step"]

    def step_sim(self) -> str:
        from mapforge.analyze.run import main as analyze
        from mapforge.simulate.run import main as simulate

        d = self.it_dir
        self.state["force_sim"] = False  # only the baseline measurement may skip the review gate
        t0 = time.time()
        import mapforge.simulate.run as sim_run
        from mapforge import skip

        maps = self.cfg.path("maps_dir")
        sim_run.CANCEL = lambda: skip.pending(maps, self.map) is not None
        try:
            # --resume: an iteration cut off while simulating goes on where it stopped
            code = simulate(["--map", self.map, "--out", str(d / "sim"), "--resume"])
        finally:
            sim_run.CANCEL = None
        sim = _load(d / "sim" / "simulation.json") or {}
        if sim.get("stop_reason") == "skipped":  # the batches so far stay on disk, unscored
            self.skip_now("sim", skip.pending(maps, self.map))
            return "decide"
        if code != 0 or not sim.get("summary"):
            self.record(reached="smoke" if not (sim.get("smoke") or {}).get("ok") else "simulate",
                        why=str(sim.get("stop_reason", "simulation failed")))  # fmt: skip
            self.state["counters"]["hard_fail"] += 1
            self.state["step"] = "decide"
            self.save()
            return "decide"
        args = ["--map", self.map, "--sim", str(d / "sim"), "--out", str(d / "analysis")]
        best = self.state.get("best")
        if best:
            args += ["--baseline", str(self.root / best["iteration"] / "analysis" / "metrics.json")]
        analyze(args)
        m = _load(d / "analysis" / "metrics.json") or {}
        # the website shows build/<map>/: keep it on the latest measurement
        for name in ("analysis",):
            if (self.build / name).exists():
                shutil.rmtree(self.build / name)
            shutil.copytree(d / name, self.build / name)
        shutil.copy2(d / "sim" / "simulation.json", self.build / "simulation.json")
        self._evaluate(m, round(time.time() - t0, 1))
        self.state["step"] = "decide"
        self.save()
        return "decide"

    def _evaluate(self, m: dict[str, Any], sim_s: float) -> None:
        c = self.state["counters"]
        c["measured"] += 1
        bot_score, delta = m.get("score"), m.get("delta") or {}
        verdict = delta.get("verdict")
        best = self.state.get("best")
        # the structural design rules count too (DESIGN_GUIDE §9): each validator warning adds to
        # the score, and "targets met" needs a map without warnings
        v = _load(self.it_dir / "validation.json") or {}
        warns = int(v.get("summary", {}).get("warnings", 0))
        # warnings Decide handed to the human (plan.structural_needs_human) still cost score, but
        # do not block reaching Gate B: the human decides them there
        human = set(self.state.get("structural_needs_human", {}))
        blocking = sum(
            1
            for f in v.get("findings", [])
            if f.get("severity") == "warning" and f.get("rule") not in human
        )
        penalty = float(self.fitness.get("design_warning_penalty", 0.15))
        score = None if bot_score is None else round(bot_score + penalty * warns, 4)
        met = bool(m.get("targets_met")) and blocking == 0
        c["targets_met"] = c["targets_met"] + 1 if met else 0
        # judged on the combined score (bot score + design warnings): a bot metric that got worse
        # beyond the noise only causes a rollback if the combined score got worse too
        improved = best is None or (score is not None and score < best["score"]
                                    and (verdict != "værre" or score < best["score"] - 0.05))  # fmt: skip
        self.state["rollback"] = bool(best) and not improved and verdict == "værre" and (
            score is None or score > best["score"])  # fmt: skip
        if improved:
            self.state["best"] = {"iteration": self.state["iteration"], "score": score}
            c["since_best"] = 0
        else:
            c["since_best"] += 1
        t = m.get("metrics", {})
        self.record(reached="simulate", score=score, bot_score=bot_score, design_warnings=warns, rounds=m.get("rounds"), verdict=verdict,
                    targets_met=m.get("targets_met"), sim_s=sim_s,
                    t_winrate=t.get("t_winrate", {}).get("value"),
                    site_split_a=t.get("site_split_a", {}).get("value"),
                    new_best=improved, rollback=self.state["rollback"])  # fmt: skip
        self.log(f"measured: score {score} ({m.get('rounds')} rounds), vs best: {verdict or '-'}"
                 f"{' -> new best' if improved else ''}{' -> ROLLBACK next' if self.state['rollback'] else ''}")  # fmt: skip

    def step_decide(self) -> int:
        from mapforge.decide.run import emit_into

        d = self.it_dir
        if not (d / "plan.json").is_file():
            # plateau / budget / targets met are known right after the measurement: stop
            # before asking for a plan that would leave the layout on an unmeasured change
            reason = self.stop_reason(True)
            if reason:
                return self.stop(reason)
        if not (d / "decide_prompt.md").is_file():
            emit_into(self.cfg, self.map, d, self.loop_context())
        if not (d / "plan.json").is_file():
            return self._await("decide", d / "decide_prompt.md", d / "plan.json")
        return self.step_apply()

    def loop_context(self) -> str:
        best = self.state.get("best")
        lines = [f"Iteration {self.state['iteration']} i et autonomt loop (startet {self.state['started']}).",
                 f"Bedste måling indtil nu: {best['iteration'] + ' (score ' + str(best['score']) + ')' if best else 'ingen'}."]  # fmt: skip
        if self.state.get("rollback"):
            lines.append(f"**Rollback:** denne måling var dårligere end den bedste ud over støjen. Din plan anvendes på "
                         f"layoutet fra iteration {best['iteration']} (runs/{self.map}/{best['iteration']}/layout.yaml), "
                         "ikke på det nuværende – prøv en anden ændring end den, der gjorde det værre.")  # fmt: skip
        lines += [
            "",
            "| iteration | nåede | score | T-winrate | A-plants | ift. bedste |",
            "|---|---|---|---|---|---|",
        ]
        for h in self.state["history"]:
            lines.append(f"| {h['iteration']} | {h.get('reached')} | {h.get('score', '–')} | {h.get('t_winrate', '–')} | "
                         f"{h.get('site_split_a', '–')} | {h.get('verdict') or '–'} |")  # fmt: skip
        lines.append(
            "\nMålinger: `analysis/report.md` og `analysis/metrics.json` (+ heatmaps) i iterationsmappen, hvis der blev simuleret."
        )
        lines += self._smoke_failure()
        if self.state.get("skipped") == self.state["iteration"]:
            lines.append("\n**This iteration was skipped by the human:** no new simulation. Carry out "
                         "the open wishes (above all the graph changes); the last measurement stays "
                         "the baseline.")  # fmt: skip
        return "\n".join(lines)

    def _smoke_failure(self) -> list[str]:
        """Why this iteration's smoke test failed (a site never reached, ...): Decide must fix
        that first, so it gets the failed checks per graph attempt, not only 'reached: smoke'."""
        sim = _load(self.it_dir / "sim" / "simulation.json") or {}
        smoke = sim.get("smoke") or {}
        if sim.get("ok", True) or not smoke:
            return []
        out = ["", "**Smoke-testen fejlede**, så der blev ikke målt. Ret det først (fx en blokeret eller "
               "for smal vej til et site); sammenlign med layoutet fra den sidste iteration, der nåede simulate."]  # fmt: skip
        for name, check in (smoke.get("checks") or {}).items():
            if not check.get("ok", True):
                detail = {k: v for k, v in check.items() if k != "ok"}
                out.append(f"- `{name}`: {json.dumps(detail, ensure_ascii=False)}")
        for a in sim.get("graph_attempts") or []:
            out.append(f"- YaPB-graf med {a.get('distance')} units mellem noder: "
                       f"bot-samples pr. site {json.dumps(a.get('samples_per_site'))}")  # fmt: skip
        return out

    def step_apply(self) -> int:
        from mapforge.decide.run import answer
        from mapforge.loop.apply import apply_plan

        d = self.it_dir
        decision = answer(self.cfg, d, float(self.cfg.data.get("decide", {}).get("phase", 6)))
        from mapforge import annotations

        plan_now = _load(self.it_dir / "plan.json") or {}
        for item in plan_now.get("structural_needs_human", []) or []:
            if isinstance(item, dict) and item.get("rule"):
                self.state.setdefault("structural_needs_human", {})[str(item["rule"])] = str(
                    item.get("reason", "")
                )
        for item in self._plan_needs_human():
            annotations.mark_needs_human(self.cfg.path("maps_dir"), self.map, self.state["iteration"],
                                         int(item["annotation"]), str(item.get("reason", "")))  # fmt: skip
        if decision.get("escalate"):
            from mapforge import annotations

            reason = decision.get("escalation_reason") or ""
            annotations.resolve(
                self.cfg.path("maps_dir"), self.map, self.state["iteration"], [], reason
            )
            self.record(decision="escalated", why=reason)
            return self.stop(f"Decide eskalerede: {decision.get('escalation_reason')}")
        best = self.state.get("best")
        base = (
            self.root / best["iteration"] / "layout.yaml"
            if (self.state.get("rollback") and best)
            else d / "layout.yaml"
        )
        new, applied, failed = apply_plan(base.read_text(encoding="utf-8"), decision["accepted"])
        (d / "applied.json").write_text(json.dumps({"base": _rel(self.cfg, base), "applied": applied, "failed": failed,
                                                    "rejected_by_policy": decision["rejected"]}, indent=2, ensure_ascii=False),
                                        encoding="utf-8")  # fmt: skip
        decision["applied"] = bool(applied)
        (d / "decision.json").write_text(
            json.dumps(decision, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (d / "layout_next.yaml").write_text(new, encoding="utf-8")
        self.layout.write_text(new, encoding="utf-8", newline="\n")
        from mapforge import annotations

        done = annotations.resolve(
            self.cfg.path("maps_dir"), self.map, self.state["iteration"], applied, None
        )
        self.record(
            applied=[a["effect"] for a in applied], failed=len(failed), annotations_done=done
        )
        self.log(f"applied {len(applied)} change(s), {len(failed)} failed, "
                 f"{len(decision['rejected'])} rejected by policy (base {base.parent.name})")  # fmt: skip
        reason = self.stop_reason(bool(applied) or self.state.get("rollback"))
        if reason:
            return self.stop(reason)
        n = int(self.state["iteration"]) + 1
        self.state.update(iteration=f"{n:03d}", step="build")
        self.it_dir.mkdir(parents=True, exist_ok=True)
        self.save()
        return -1  # go on

    def _plan_needs_human(self) -> list[dict[str, Any]]:
        """Wishes Decide could not fulfil (plan.needs_human): marked, the loop goes on."""
        plan = _load(self.it_dir / "plan.json") or {}
        out = []
        for item in plan.get("needs_human", []) or []:
            ref = str(item.get("annotation", "")).removeprefix("annotation:")
            if ref.isdigit():
                out.append({**item, "annotation": ref})
        return out

    def stop_reason(self, changed: bool) -> str | None:
        stop, budget = self.fitness.get("stop", {}), self.fitness.get("budget", {})
        c = self.state["counters"]
        done_its = int(self.state["iteration"]) - int(self.state["first_iteration"]) + 1
        from mapforge import annotations

        wishes = [
            a
            for a in annotations.load(self.cfg.path("maps_dir"), self.map)
            if a["status"] == "open"
        ]
        if c["targets_met"] >= int(stop.get("targets_met_in_a_row", 2)) and not wishes:
            return f"alle mål ramt i {c['targets_met']} målinger i træk → Gate B"
        if c["hard_fail"] >= int(stop.get("hard_fail_in_a_row", 3)):
            return f"hårde krav fejlede {c['hard_fail']} gange i træk → eskalér til mennesket"
        if c["review_fail"] >= int(stop.get("review_fail_in_a_row", 5)):
            return f"review fejlede {c['review_fail']} gange i træk → eskalér til mennesket"
        if c["measured"] and c["since_best"] >= int(stop.get("plateau_iterations", 5)):
            return f"plateau: ingen forbedring i {c['since_best']} målinger"
        if done_its >= int(budget.get("max_iterations", 20)):
            return f"budget: {done_its} iterationer"
        hours = self.state.get("active_s", 0.0) / 3600
        if hours >= float(budget.get("max_wall_clock_h", 12)):
            return f"budget: {hours:.1f} timers aktiv køretid"
        if not changed and not (
            c["targets_met"] and self.state["history"][-1].get("reached") == "simulate"
        ):
            refused = self._refused()
            if refused:  # Decide did propose: say what stood in the way, not "nothing proposed"
                return (f"ingen af Decides ændringer kunne anvendes ({refused}) → mennesket "
                        f"(se runs/{self.map}/{self.state['iteration']}/applied.json)")  # fmt: skip
            return "Decide foreslog ingen ændringer (og målene er ikke ramt) → mennesket"
        return None

    def _refused(self) -> str:
        """Why this iteration's proposed changes were not applied ('' if none were proposed)."""
        if "iteration" not in self.state:
            return ""
        a = _load(self.it_dir / "applied.json") or {}
        why = [f"{x['type']}: {x.get('reason', '?')}" for x in a.get("failed", [])]
        why += [f"{x['type']}: {x.get('reason', '?')}" for x in a.get("rejected_by_policy", [])]
        return "; ".join(why)[:300]

    def _await(self, what: str, prompt: Path, answer: Path) -> int:
        self.state["awaiting"] = {
            "step": what,
            "prompt": _rel(self.cfg, prompt),
            "answer": _rel(self.cfg, answer),
        }
        self.save()
        self.log(
            f"AWAITING {what}: read {_rel(self.cfg, prompt)} -> write {_rel(self.cfg, answer)}, then run the loop again"
        )
        return AWAIT

    # ---------------------------------------------------------------- driver
    def run(self) -> int:
        if not self.state:
            raise RuntimeError("no loop state: start with --init")
        if self._closed():
            return self.stop(
                "banen er afsluttet (Input på map-siden) – genåbn den for at fortsætte"
            )
        if self.state.get("status") == "stopped":
            self.log(f"already stopped: {self.state.get('stop_reason')}")
            return 0
        self.state.pop("awaiting", None)
        self._mark = time.time()  # active time starts now (see save)
        while True:
            self.check_skip()
            step = self.state["step"]
            if step == "build":
                self.step_build()
            elif step == "review":
                r = self.step_review()
                if r == AWAIT:
                    return AWAIT
            elif step == "sim":
                self.step_sim()
            elif step == "decide":
                r = self.step_decide()
                if r in (AWAIT, 0):
                    return r
            else:
                raise RuntimeError(f"unknown step {step!r}")

    def report(self) -> str:
        s = self.state
        human = s.get("structural_needs_human") or {}
        best = s.get("best")
        lines = [f"# Loop – {s.get('map')}", "",
                 f"Status: **{s.get('status')}**" + (f" – {s.get('stop_reason')}" if s.get("stop_reason") else ""),
                 f"Startet {s.get('started')} · opdateret {s.get('updated')} · aktiv køretid {s.get('active_s', 0) / 3600:.1f} t"
                 f" · nu: iteration {s.get('iteration')}, trin {s.get('step')}",
                 f"Bedste måling: {best['iteration'] + ' (score ' + str(best['score']) + ')' if best else '–'}", "",
                 "| iteration | nåede | review | score | T-winrate | A-plants | ift. bedste | ændringer |",
                 "|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for h in s.get("history", []):
            lines.append(f"| {h['iteration']} | {h.get('reached')} | {h.get('review', '–')} | {h.get('score', '–')} | "
                         f"{h.get('t_winrate', '–')} | {h.get('site_split_a', '–')} | {h.get('verdict') or '–'} | "
                         f"{'; '.join(h.get('applied', [])) or '–'} |")  # fmt: skip
        if human:
            lines += ["", "## Strukturelle punkter til mennesket (Gate B)"]
            lines += [f"- `{k}`: {v}" for k, v in human.items()]
        if s.get("awaiting"):
            a = s["awaiting"]
            lines += ["", f"Venter på **{a['step']}**: læs `{a['prompt']}`, skriv `{a['answer']}`."]
        return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--map", required=True)
    parser.add_argument("--init", action="store_true", help="start a new loop (first iteration)")
    parser.add_argument("--force-sim", action="store_true",
                        help="with --init: measure the first iteration even if review fails (baseline)")  # fmt: skip
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", metavar="REASON", help="stop the loop by hand (a person decided)")
    args = parser.parse_args(argv)
    cfg = load_config()
    loop = Loop(cfg, args.map)
    try:
        if args.stop:
            if not loop.state:
                raise RuntimeError(f"no loop for {args.map}")
            return loop.stop(f"stoppet manuelt: {args.stop}")
        if args.status:
            print(loop.report() if loop.state else f"no loop for {args.map}")
            return 0
        if args.init and loop.state.get("status") == "running":
            raise RuntimeError(f"a loop is already running for {args.map} ({loop.state_file})")
        if problem := docker_problem():
            raise RuntimeError(problem)
        if args.init:
            loop.init(args.force_sim)
        return loop.run()
    except RuntimeError as exc:
        print(f"loop failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from mapforge.site.build import refresh_site  # lazy: avoids an import cycle

    code = main()
    refresh_site()
    sys.exit(code)
