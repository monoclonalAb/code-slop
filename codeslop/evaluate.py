"""Hidden-test evaluation, mirroring SlopCodeBench's pytest runner.

- tests for checkpoints 1..N are copied into `.evaluation_tests/` of a *copy* of the snapshot
- deps: `uv init --bare` + `uv add -r requirements.txt`; entrypoint `uv run <entry>.py`
- groups: tests from earlier checkpoint files -> regression; else marker error/functionality,
  otherwise core.  strict = everything passes; iso = all non-regression pass; core = all core pass.
"""

from __future__ import annotations

import json
import shlex
import shutil
from pathlib import Path

from codeslop import docker
from codeslop.problems import Problem

TEST_DIR = ".evaluation_tests"
REPORT = ".scbench/pytest-report.json"
TEST_DEPS = ["pytest", "pytest-json-report", "pytest-timeout", "jsonschema", "deepdiff"]
SNAPSHOT_IGNORE = shutil.ignore_patterns(".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache",
                                         TEST_DIR, ".scbench", ".pi", ".ruff_cache", ".mypy_cache")


def _copy_tests(problem: Problem, checkpoint: str, dest: Path) -> None:
    upto = problem.checkpoints[: problem.checkpoint_index(checkpoint)]
    wanted = {f"test_{c}.py" for c in upto}
    dest.mkdir(parents=True)
    for item in (problem.path / "tests").iterdir():
        if item.name == "__pycache__":
            continue
        if item.is_dir():
            shutil.copytree(item, dest / item.name)
        elif item.name.startswith("test_") and item.suffix == ".py":
            if item.name in wanted:
                shutil.copy2(item, dest / item.name)
        else:
            shutil.copy2(item, dest / item.name)


def _group(nodeid: str, keywords: list[str], checkpoint: str) -> str:
    file = nodeid.split("::", 1)[0].rsplit("/", 1)[-1]
    if file.startswith("test_checkpoint_") and file != f"test_{checkpoint}.py":
        return "regression"
    if "error" in keywords:
        return "error"
    if "regression" in keywords:
        return "regression"
    if "functionality" in keywords:
        return "functionality"
    return "core"


def evaluate(problem: Problem, checkpoint: str, snapshot: Path, out_dir: Path,
             *, timeout_s: float = 1800) -> dict:
    eval_ws = out_dir / "eval_workspace"
    if eval_ws.exists():
        shutil.rmtree(eval_ws)
    shutil.copytree(snapshot, eval_ws, ignore=SNAPSHOT_IGNORE)
    _copy_tests(problem, checkpoint, eval_ws / TEST_DIR)
    # Like SCB: static assets also go to .evaluation_tests/assets/<name>/ (+ env vars) for the tests.
    env = {}
    for name, _save, src in problem.static_assets:
        target = eval_ws / TEST_DIR / "assets" / name
        if src.is_dir():
            shutil.copytree(src, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        env[f"SCBENCH_ASSET_{name.upper()}"] = f"{TEST_DIR}/assets/{name}"
    if env:
        env["SCBENCH_ASSETS_DIR"] = f"{TEST_DIR}/assets"
    (eval_ws / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    core: core\n    functionality: functionality\n"
        "    error: error\n    regression: regression\n")
    (eval_ws / ".scbench").mkdir(exist_ok=True)

    deps = [*TEST_DEPS, *problem.test_dependencies]
    pytest = ["uvx", *[f"--with={d}" for d in deps], "pytest",
              f"--timeout={max(60, problem.timeout * 3)}",
              f"--entrypoint=uv run {problem.entry_py}", f"--checkpoint={checkpoint}",
              f"--confcutdir={TEST_DIR}", "-p", "no:cacheprovider", "--json-report",
              f"--json-report-file={REPORT}", "--json-report-omit=traceback",
              "--json-report-omit=streams", "--json-report-omit=log",
              "--json-report-omit=collectors", "--json-report-omit=warnings", "-q", TEST_DIR]
    script = ("uv init -q --bare --no-workspace >/dev/null 2>&1 || true; "
              "if [ -f requirements.txt ]; then uv add -q -r requirements.txt "
              ">.scbench/uv-add.log 2>&1 || echo UV_ADD_FAILED; fi; "
              + " ".join(shlex.quote(p) for p in pytest))
    res = docker.run(["bash", "-lc", script], mounts={eval_ws: "/eval"}, workdir="/eval",
                     env=env, timeout=timeout_s, cpus="2", memory="4g")
    (out_dir / "eval_stdout.txt").write_text(res.stdout[-200_000:])
    (out_dir / "eval_stderr.txt").write_text(res.stderr[-200_000:])

    summary: dict = {"checkpoint": checkpoint, "timed_out": res.timed_out,
                     "uv_add_failed": "UV_ADD_FAILED" in res.stdout}
    report_path = eval_ws / REPORT
    if not report_path.exists():
        summary.update(error="no pytest report", strict=False, iso=False, core=False)
        _finish(summary, out_dir, eval_ws)
        return summary

    report = json.loads(report_path.read_text())
    groups: dict[str, dict[str, int]] = {}
    for test in report.get("tests", []):
        g = _group(test["nodeid"], list(test.get("keywords") or []), checkpoint)
        bucket = groups.setdefault(g, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += test.get("outcome") == "passed"
    total = sum(b["total"] for b in groups.values())
    passed = sum(b["passed"] for b in groups.values())
    non_reg = [b for g, b in groups.items() if g != "regression"]

    def all_pass(bs):
        return bool(bs) and all(b["passed"] == b["total"] for b in bs)

    summary.update(
        groups=groups, tests_total=total, tests_passed=passed,
        pass_rate=round(passed / total, 4) if total else 0.0,
        strict=total > 0 and passed == total,
        iso=all_pass(non_reg),
        core=all_pass([groups["core"]] if "core" in groups else []),
        **{f"{g}_pass_rate": round(b["passed"] / b["total"], 4) for g, b in groups.items() if b["total"]},
    )
    _finish(summary, out_dir, eval_ws)
    return summary


def _finish(summary: dict, out_dir: Path, eval_ws: Path) -> None:
    report = eval_ws / REPORT
    if report.exists():
        shutil.copy2(report, out_dir / "pytest_report.json")
    shutil.rmtree(eval_ws, ignore_errors=True)
    (out_dir / "eval.json").write_text(json.dumps(summary, indent=2))
