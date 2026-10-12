"""codeslop CLI.

  codeslop doctor [--live] [--models opus-5.5,gpt-6.1-sol]
  codeslop build-image
  codeslop list-problems
  codeslop verify-reference <problem> [--checkpoint N]
  codeslop run <experiment.yaml> [--jobs N] [--models a,b] [--arms x,y] [--dry-run]
  codeslop report <runs/<experiment>>
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from codeslop import arms as arms_mod
from codeslop import auth
from codeslop import docker
from codeslop.config import CACHE_DIR
from codeslop.config import IMAGE
from codeslop.config import PINS
from codeslop.config import RUNS_DIR
from codeslop.config import load_experiment
from codeslop.config import load_models

_print_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


def cmd_doctor(args) -> int:
    from codeslop.agent import run_pi
    from codeslop.problems import ensure_problems_repo

    models, providers = load_models()
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        log(f"  [{'ok' if cond else '!!'}] {name}{(' - ' + detail) if detail else ''}")

    log(f"pins: {json.dumps(PINS)}")
    up = docker.docker_ok()
    check("docker daemon reachable", up, "" if up else "start OrbStack / Docker Desktop")
    have = up and docker.image_exists()
    check(f"image {IMAGE}", have, "" if have else "run `codeslop build-image`")
    check("host pi on PATH (for token refresh)", shutil.which("pi"))
    for provider, pcfg in providers.items():
        try:
            if auth.mode(pcfg) == "api_key":
                check(f"auth {provider}", True, f"API key from ${pcfg['api_key_env']}")
            else:
                check(f"auth {provider}", True,
                      f"pi OAuth login, token valid {auth.hours_left(provider):.1f} h")
        except RuntimeError as e:
            check(f"auth {provider}", False, str(e))
    try:
        root = ensure_problems_repo()
        check("scb-problems checkout", True, str(root))
    except Exception as e:  # noqa: BLE001
        check("scb-problems checkout", False, str(e))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for tool in (["uvx", "-q", "scb-check==" + PINS["scb_check"], "--version"],
                 ["uvx", "-q", "ruff==" + PINS["ruff"], "--version"]):
        r = subprocess.run(tool, capture_output=True, text=True, cwd=CACHE_DIR)
        check(" ".join(tool[2:3]), r.returncode == 0, (r.stdout or r.stderr).strip()[:60])

    if args.live:
        from codeslop.config import ModelSpec

        if args.models:
            targets = [models[k] for k in args.models.split(",")]
        else:  # cheapest model per provider
            targets = [ModelSpec(f"{p}-canary", p, cfg["refresh_model"], "low")
                       for p, cfg in providers.items()]
        for m in targets:
            with tempfile.TemporaryDirectory(prefix="canary-", dir=CACHE_DIR) as tmp:
                ws, out = Path(tmp) / "ws", Path(tmp) / "out"
                ws.mkdir()
                (ws / "AGENTS.md").write_text("The project codename is PELICAN-42.\n")
                res = run_pi(ws, "What is the project codename from your project instructions? "
                             "Answer with only the codename.", m, out, timeout_s=300,
                             provider_cfg=providers[m.provider])
                good = "PELICAN-42" in res.final_text
                check(f"live: {m.provider}/{m.id} in container reads AGENTS.md", good,
                      res.error or res.final_text.strip()[:60])
    log("all good" if ok else "some checks failed")
    return 0 if ok else 1


def cmd_build_image(args) -> int:
    docker.build_image()
    return 0


def cmd_list_problems(args) -> int:
    from codeslop.problems import list_problems
    from codeslop.problems import load_problem

    for name in list_problems():
        p = load_problem(name)
        log(f"{name:<28} {len(p.checkpoints)} checkpoints  entry={p.entry_py}")
    return 0


def cmd_verify_reference(args) -> int:
    """Evaluate the reference solution itself (sanity check of the eval pipeline, no LLM)."""
    from codeslop import metrics
    from codeslop.evaluate import evaluate
    from codeslop.problems import load_problem
    from codeslop.problems import seed_workspace

    problem = load_problem(args.problem)
    cps = [args.checkpoint] if args.checkpoint else range(1, len(problem.checkpoints) + 1)
    rc = 0
    for n in cps:
        with tempfile.TemporaryDirectory(prefix="ref-", dir=CACHE_DIR) as tmp:
            ws, out = Path(tmp) / "ws", Path(tmp) / "out"
            seed_workspace(problem, n, ws)
            ev = evaluate(problem, f"checkpoint_{n}", ws, out)
            m = metrics.measure(ws, problem.asset_paths)
            log(f"{problem.name} checkpoint_{n}: strict={ev.get('strict')} iso={ev.get('iso')} "
                f"pass={ev.get('tests_passed')}/{ev.get('tests_total')} "
                f"verb={m.get('verbosity')} eros={m.get('erosion')} stmts={m.get('stmts')}"
                + (f" ERROR={ev.get('error')}" if ev.get("error") else ""))
            rc |= not ev.get("strict")
    return int(rc)


def cmd_run(args) -> int:
    from codeslop.runner import plan
    from codeslop.runner import run_experiment

    exp = load_experiment(Path(args.experiment))
    if args.models:
        exp.models = args.models.split(",")
    if args.arms:
        exp.arms = args.arms.split(",")
    models, providers = load_models()
    unknown = [m for m in exp.models if m not in models]
    if unknown:
        log(f"unknown models: {unknown} (see configs/models.yaml)")
        return 2
    errs = arms_mod.missing(exp.arms, [p.name for p in exp.problems])
    if errs:
        log("arm material missing:\n  " + "\n  ".join(errs))
        return 2
    trajectories = plan(exp, models)
    n_cp = 0
    from codeslop.problems import load_problem
    for t in trajectories:
        total = len(load_problem(t.problem.name).checkpoints) - t.problem.start
        n_cp += min(total, t.problem.max_checkpoints or total)
    log(f"experiment '{exp.name}': {len(trajectories)} trajectories, {n_cp} agent checkpoints, "
        f"jobs={args.jobs or exp.jobs}, timeout={exp.timeout_minutes}min/checkpoint")
    if args.dry_run:
        for t in trajectories:
            log(f"  {t.label}  (start=checkpoint_{t.problem.start})")
        return 0
    if not docker.image_exists():
        log("building image ...")
        docker.build_image()
    results = run_experiment(exp, models, providers, jobs=args.jobs, log=log)
    failed = [r for r in results if r["status"].startswith("failed")]
    log(f"done: {len(results) - len(failed)} ok, {len(failed)} failed. "
        f"Run `codeslop report {RUNS_DIR / exp.name}`")
    return 1 if failed else 0


def cmd_report(args) -> int:
    from codeslop.report import report

    log(report(Path(args.exp_dir)))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="codeslop", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="check docker, image, pi logins, tools")
    d.add_argument("--live", action="store_true", help="also run a tiny in-container canary per provider")
    d.add_argument("--models", help="comma-separated model keys for --live (default: cheap refresh models)")
    d.set_defaults(fn=cmd_doctor)
    sub.add_parser("build-image").set_defaults(fn=cmd_build_image)
    sub.add_parser("list-problems").set_defaults(fn=cmd_list_problems)
    v = sub.add_parser("verify-reference", help="evaluate a reference solution (no LLM)")
    v.add_argument("problem")
    v.add_argument("--checkpoint", type=int)
    v.set_defaults(fn=cmd_verify_reference)
    r = sub.add_parser("run", help="run an experiment matrix")
    r.add_argument("experiment")
    r.add_argument("--jobs", type=int)
    r.add_argument("--models", help="override the experiment's models (comma-separated keys)")
    r.add_argument("--arms", help="override the experiment's arms (comma-separated)")
    r.add_argument("--dry-run", action="store_true")
    r.set_defaults(fn=cmd_run)
    rp = sub.add_parser("report", help="aggregate results")
    rp.add_argument("exp_dir")
    rp.set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
