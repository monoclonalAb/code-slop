#!/usr/bin/env python3
"""Measurement-validity probes for SlopCodeBench-style sloppiness metrics.

Reproduces the pilot findings in ../AUDIT.md:
  P1  tool-version drift      (same code, different scb-check releases)
  P2  formatting sensitivity  (same AST, different ruff line lengths)
  P3  reference-solution band (benchmark's own solutions, first vs last checkpoint)

Also provides `canonical_measure()`: the measurement protocol proposed in the
audit (strip tests -> canonical format -> pinned scb-check -> AST-based size).

Usage:
  uv run --with pandas python pilot/measure.py [--workdir /tmp/slop-pilot]
Requires: git, uv/uvx on PATH. No API keys, no Docker.
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path

SCB_VERSIONS = ["0.1.0", "0.1.3", "0.2.0"]
PINNED_SCB = "0.1.3"  # version pinned by slop-code-bench @ 31ceea3
RUFF_VERSION = "0.16.10"
SCB_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "scb-check.toml"
FLASK = ("https://github.com/pallets/flask", "d73fa1cdcbd8b1465c151db8924ba58b1dd14e35")
SCB_PROBLEMS = ("https://github.com/gabeorlanski/scb-problems", "38d627ecf668a88f88f8d260f8df8df6116e9b03")


def sh(cmd: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout


def clone(url: str, commit: str, dest: Path) -> Path:
    if not dest.exists():
        sh(["git", "clone", "-q", url, str(dest)])
    sh(["git", "checkout", "-q", commit], cwd=dest)
    return dest


def scb_check(path: Path, version: str = PINNED_SCB) -> dict:
    # scb-check >=0.2.0 exits non-zero when it finds violations but still emits the report.
    # Explicit config + neutral cwd: scb-check otherwise reads [tool.ruff] excludes from any
    # pyproject.toml above the *working directory* (see AUDIT.md P4).
    proc = subprocess.run(
        ["uvx", "-q", f"scb-check=={version}", "check", "--report", "--include-all",
         "--config", str(SCB_CONFIG), str(path)],
        capture_output=True, text=True, cwd=tempfile.gettempdir(),
    )
    try:
        r = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr) from e
    return {k: r.get(k) for k in ("verbosity", "erosion", "total_loc", "clone_loc", "verbosity_flagged_loc")}


def logical_size(path: Path) -> int:
    """Format-invariant size: number of AST statement nodes across .py files."""
    n = 0
    for f in path.rglob("*.py"):
        try:
            tree = ast.parse(f.read_text(errors="ignore"))
        except SyntaxError:
            continue
        n += sum(isinstance(node, ast.stmt) for node in ast.walk(tree))
    return n


def ruff_format(path: Path, line_length: int = 88) -> None:
    subprocess.run(
        ["uvx", "-q", f"ruff=={RUFF_VERSION}", "format", "--no-cache", "--line-length", str(line_length), str(path)],
        check=False, capture_output=True,
    )


def canonical_measure(src: Path, scratch: Path, version: str = PINNED_SCB) -> dict:
    """Proposed protocol: copy, drop tests/venvs, canonical format, pinned metric, AST size."""
    if scratch.exists():
        shutil.rmtree(scratch)
    shutil.copytree(src, scratch, ignore=shutil.ignore_patterns(
        "tests", "test_*", "*_test.py", ".venv", "venv", "__pycache__", ".git"))
    ruff_format(scratch, 88)
    res = scb_check(scratch, version)
    res["logical_stmts"] = logical_size(scratch)
    return res


def fmt(r: dict) -> str:
    return (f"verb={r['verbosity']:.3f} eros={r['erosion']:.3f} "
            f"loc={r['total_loc']} clone={r['clone_loc']} flagged={r['verbosity_flagged_loc']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default="/tmp/slop-pilot")
    ap.add_argument("--out", default=str(Path(__file__).parent / "results.json"))
    args = ap.parse_args()
    wd = Path(args.workdir)
    wd.mkdir(parents=True, exist_ok=True)
    results: dict = {}

    flask = clone(*FLASK, wd / "flask")

    print("P1  tool-version drift on flask/src (paper v2 reports verb=0.111 eros=0.209)")
    results["P1_version_drift"] = {}
    for v in SCB_VERSIONS:
        r = scb_check(flask / "src", v)
        results["P1_version_drift"][v] = r
        print(f"    scb-check {v}: {fmt(r)}")

    print("P2  formatting sensitivity on flask/src (identical AST)")
    results["P2_formatting"] = {}
    for ll in (60, 88, 200):
        d = wd / f"flask_fmt{ll}"
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(flask / "src", d)
        ruff_format(d, ll)
        r = scb_check(d)
        r["logical_stmts"] = logical_size(d)
        results["P2_formatting"][ll] = r
        print(f"    line-length {ll:>3}: {fmt(r)} stmts={r['logical_stmts']}")

    print("P3  reference solutions, canonical protocol (first vs last checkpoint)")
    probs = clone(*SCB_PROBLEMS, wd / "scb-problems")
    rows = []
    for pdir in sorted(p for p in probs.iterdir() if (p / "solutions").is_dir()):
        cps = sorted((p for p in (pdir / "solutions").glob("checkpoint_*") if p.is_dir()),
                     key=lambda p: int(p.name.split("_")[1]))
        if not cps:
            continue
        for tag, cp in (("first", cps[0]), ("last", cps[-1])):
            try:
                r = canonical_measure(cp, wd / "scratch" / f"{pdir.name}_{tag}")
            except subprocess.CalledProcessError:
                continue
            rows.append({"problem": pdir.name, "which": tag, "checkpoint": cp.name, "n_checkpoints": len(cps), **r})
            print(f"    {pdir.name:<28} {tag:<5} {fmt(r)}")
    results["P3_reference_solutions"] = rows

    def agg(which: str, key: str) -> tuple[float, float]:
        xs = [r[key] for r in rows if r["which"] == which and r[key] is not None]
        return statistics.mean(xs), statistics.stdev(xs)

    summary = {w: {k: agg(w, k) for k in ("verbosity", "erosion")} for w in ("first", "last")}
    results["P3_summary"] = summary
    for w, s in summary.items():
        print(f"    {w:<5} mean±sd  verbosity {s['verbosity'][0]:.3f}±{s['verbosity'][1]:.3f}"
              f"  erosion {s['erosion'][0]:.3f}±{s['erosion'][1]:.3f}")
    print("    (paper v2: human repos 0.19±0.11 / 0.34±0.22; agent checkpoints 0.44±0.18 / 0.68±0.20)")

    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
