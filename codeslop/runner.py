"""Trajectory orchestration.

A trajectory = (problem, model, arm, seed). It starts "brownfield": the workspace is the reference
solution at checkpoint_<start>; the agent then implements checkpoints start+1 .. n in order,
building on its own code, with a fresh pi context per checkpoint (as in SlopCodeBench).

runs/<experiment>/<problem>/<model>/<arm>/seed<k>/
    seed_snapshot/  seed_metrics.json  arm_material/ (autogen only)
    checkpoint_<n>/ prompt.txt agent.json agent_events.jsonl snapshot/ eval.json result.json
    DONE
"""

from __future__ import annotations

import json
import shutil
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import as_completed
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Template

from codeslop import arms as arms_mod
from codeslop import docker
from codeslop import metrics
from codeslop.agent import run_pi
from codeslop.config import PINS
from codeslop.config import PROMPTS_DIR
from codeslop.config import RUNS_DIR
from codeslop.config import Experiment
from codeslop.config import ModelSpec
from codeslop.config import ProblemRun
from codeslop.evaluate import evaluate
from codeslop.problems import Problem
from codeslop.problems import load_problem
from codeslop.problems import seed_workspace


@dataclass(frozen=True)
class Trajectory:
    experiment: str
    problem: ProblemRun
    model: ModelSpec
    arm: str
    seed: int

    @property
    def dir(self) -> Path:
        return RUNS_DIR / self.experiment / self.problem.name / self.model.key / self.arm / f"seed{self.seed}"

    @property
    def label(self) -> str:
        return f"{self.problem.name}/{self.model.key}/{self.arm}/seed{self.seed}"


def plan(exp: Experiment, models: dict[str, ModelSpec]) -> list[Trajectory]:
    return [Trajectory(exp.name, p, models[m], a, s)
            for p in exp.problems for m in exp.models for a in exp.arms for s in exp.seeds]


def _setup_venv(workspace: Path) -> None:
    """Like SCB's resume_commands: a venv with the seed's requirements, for the agent to keep using."""
    docker.run(["bash", "-lc", "python -m venv .venv && "
                "( [ -f requirements.txt ] && .venv/bin/pip install -q -r requirements.txt || true )"],
               mounts={workspace: "/workspace"}, timeout=900)


def _autogen_agents_md(t: Trajectory, workspace: Path, provider_cfgs: dict, timeout_s: float) -> Path:
    """/init-style pass by the model under test on the seed workspace; keep only its AGENTS.md."""
    material = t.dir / "arm_material"
    scratch = t.dir / "autogen_workspace"
    metrics.copy_snapshot(workspace, scratch)
    prompt = (PROMPTS_DIR / "init.jinja").read_text()
    res = run_pi(scratch, prompt, t.model, t.dir / "autogen", timeout_s=timeout_s,
                 provider_cfg=provider_cfgs[t.model.provider], load_context_files=False)
    produced = scratch / "AGENTS.md"
    if not produced.exists():
        raise RuntimeError(f"autogen produced no AGENTS.md (agent error: {res.error})")
    material.mkdir(parents=True, exist_ok=True)
    shutil.copy2(produced, material / "AGENTS.md")
    shutil.rmtree(scratch, ignore_errors=True)
    return material / "AGENTS.md"


def run_trajectory(t: Trajectory, *, prompt_template: str, timeout_s: float,
                   provider_cfgs: dict, log=print) -> dict:
    if (t.dir / "DONE").exists():
        return {"label": t.label, "status": "skipped (done)"}
    problem = load_problem(t.problem.name)
    arm = arms_mod.ARMS[t.arm]
    excludes = problem.asset_paths
    todo = list(problem.checkpoints[t.problem.start:])
    if t.problem.max_checkpoints:
        todo = todo[: t.problem.max_checkpoints]
    if not todo:
        raise ValueError(f"{problem.name}: nothing to run after checkpoint_{t.problem.start}")

    # Fresh start (partial trajectories are restarted from scratch for cleanliness).
    if t.dir.exists():
        shutil.rmtree(t.dir)
    workspace = t.dir / "workspace"
    workspace.mkdir(parents=True)
    seed_workspace(problem, t.problem.start, workspace)
    seed_snap = t.dir / "seed_snapshot"
    metrics.copy_snapshot(workspace, seed_snap)
    seed_m = metrics.measure(seed_snap, excludes)
    (t.dir / "seed_metrics.json").write_text(json.dumps(seed_m, indent=2))
    _setup_venv(workspace)

    autogen_md = None
    if arm.agents == "autogen":
        autogen_md = _autogen_agents_md(t, workspace, provider_cfgs, timeout_s)
    material = arms_mod.material(arm, problem.name, autogen_md)

    template = Template((PROMPTS_DIR / prompt_template).read_text())
    prev_snap, prev_m = seed_snap, seed_m
    rows = []
    for i, cp in enumerate(todo):
        cp_dir = t.dir / cp
        arms_mod.apply(arm, workspace, material, first=(i == 0))
        before = arms_mod.context_fingerprint(workspace)
        prompt = template.render(spec=problem.spec(cp), is_continuation=True)
        log(f"[{t.label}] {cp}: agent running ...")
        res = run_pi(workspace, prompt, t.model, cp_dir, timeout_s=timeout_s,
                     provider_cfg=provider_cfgs[t.model.provider],
                     load_context_files=arm.loads_context)
        after = arms_mod.context_fingerprint(workspace)

        snap = cp_dir / "snapshot"
        metrics.copy_snapshot(workspace, snap)
        log(f"[{t.label}] {cp}: evaluating ...")
        ev = evaluate(problem, cp, snap, cp_dir)
        m = metrics.measure(snap, excludes)
        row = {
            "experiment": t.experiment, "problem": problem.name, "model": t.model.key,
            "provider": t.model.provider, "model_id": t.model.id, "arm": t.arm, "seed": t.seed,
            "start_checkpoint": t.problem.start, "checkpoint": cp,
            "checkpoint_index": problem.checkpoint_index(cp), "step": i + 1, "steps_total": len(todo),
            **{f"agent_{k}": v for k, v in res.to_dict().items() if k != "final_text"},
            "context_files_edited_by_agent": before != after,
            **{f"eval_{k}": v for k, v in ev.items() if k != "groups"},
            **{f"q_{k}": v for k, v in m.items()},
            **{f"step_{k}": v for k, v in metrics.marginal(prev_m, m).items()},
            **{f"cum_{k}": v for k, v in metrics.marginal(seed_m, m).items()},
            **{f"churn_{k}": v for k, v in metrics.churn(prev_snap, snap, excludes).items()},
            "pins": PINS, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (cp_dir / "result.json").write_text(json.dumps(row, indent=2))
        rows.append(row)
        log(f"[{t.label}] {cp}: iso={ev.get('iso')} pass={ev.get('pass_rate')} "
            f"verb={m.get('verbosity')} eros={m.get('erosion')} "
            f"cost=${res.cost_usd_list_price:.2f} {res.wall_s:.0f}s"
            + (f" ERROR: {res.error}" if res.error else ""))
        prev_snap, prev_m = snap, m
        if res.timed_out or (res.exit_code != 0 and res.assistant_messages == 0):
            log(f"[{t.label}] stopping trajectory after agent failure at {cp}")
            break

    shutil.rmtree(workspace / ".venv", ignore_errors=True)
    (t.dir / "DONE").write_text(json.dumps({"checkpoints": len(rows)}))
    return {"label": t.label, "status": "done", "checkpoints": len(rows)}


def run_experiment(exp: Experiment, models: dict[str, ModelSpec], providers: dict,
                   *, jobs: int | None = None, log=print) -> list[dict]:
    trajectories = plan(exp, models)
    timeout_s = exp.timeout_minutes * 60
    results = []

    def one(t: Trajectory):
        try:
            return run_trajectory(t, prompt_template=exp.prompt, timeout_s=timeout_s,
                                  provider_cfgs=providers, log=log)
        except Exception as exc:  # keep the matrix going; record the failure
            t.dir.mkdir(parents=True, exist_ok=True)
            (t.dir / "FAILED").write_text(traceback.format_exc())
            log(f"[{t.label}] FAILED: {exc}")
            return {"label": t.label, "status": f"failed: {exc}"}

    with ThreadPoolExecutor(max_workers=jobs or exp.jobs) as pool:
        futures = [pool.submit(one, t) for t in trajectories]
        for f in as_completed(futures):
            results.append(f.result())
    return results
