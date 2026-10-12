"""Code-quality metrics under the canonical protocol from AUDIT.md §3.

measure():  copy code-only files -> ruff format (pinned, --isolated) -> scb-check (pinned,
            explicit config, neutral cwd) + AST statement count.
marginal(): quality of what changed between two snapshots, from scb-check's counters
            (e.g. marginal verbosity = Δflagged_loc / Δtotal_loc) - the "diff-scoped" view, so
            inherited reference code doesn't dominate the score.
churn():    lines added/removed in code files (difflib).
"""

from __future__ import annotations

import ast
import difflib
import fnmatch
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from codeslop.config import CACHE_DIR
from codeslop.config import RUFF_VERSION
from codeslop.config import SCB_CHECK_CONFIG
from codeslop.config import SCB_CHECK_VERSION

# Excluded from code metrics: tests (tracked separately), docs/context files, envs, caches.
EXCLUDE_DIRS = {"tests", "test", ".evaluation_tests", "docs", ".venv", "venv", "__pycache__",
                ".git", ".scbench", ".pi", ".ruff_cache", ".mypy_cache", ".pytest_cache",
                "node_modules", "build", "dist"}
TEST_FILE_GLOBS = ("test_*.py", "*_test.py", "conftest.py")
SCB_KEYS = ("verbosity", "erosion", "cog_erosion", "total_loc", "verbosity_flagged_loc",
            "clone_loc", "ast_grep_flagged_loc", "trivial_wrappers", "total_functions",
            "high_cc_functions", "total_mass", "high_cc_mass")


def _iter_py(root: Path, extra_excludes: tuple[str, ...] = ()):
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        parts = rel.parts
        if any(p in EXCLUDE_DIRS for p in parts[:-1]):
            continue
        if any(rel.as_posix() == e or rel.as_posix().startswith(e.rstrip("/") + "/")
               for e in extra_excludes):
            continue
        yield rel, path


def _is_test(rel: Path) -> bool:
    return any(fnmatch.fnmatch(rel.name, g) for g in TEST_FILE_GLOBS)


def code_files(root: Path, extra_excludes: tuple[str, ...] = ()) -> dict[str, str]:
    return {rel.as_posix(): p.read_text(errors="ignore")
            for rel, p in _iter_py(root, extra_excludes) if not _is_test(rel)}


def test_loc(root: Path) -> int:
    n = 0
    for path in root.rglob("*.py"):
        rel = path.relative_to(root)
        if any(p in {".venv", "venv", ".evaluation_tests", "__pycache__"} for p in rel.parts):
            continue
        if _is_test(rel) or "tests" in rel.parts[:-1]:
            n += sum(1 for line in path.read_text(errors="ignore").splitlines() if line.strip())
    return n


def _stmts(files: dict[str, str]) -> int:
    n = 0
    for src in files.values():
        try:
            n += sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(src)))
        except SyntaxError:
            pass
    return n


def _scb_check(path: Path) -> dict:
    # Neutral cwd + explicit config: scb-check otherwise reads excludes from pyproject.toml files
    # above the working directory. Exit code is non-zero when findings exist; parse stdout anyway.
    proc = subprocess.run(
        ["uvx", "-q", f"scb-check=={SCB_CHECK_VERSION}", "check", "--report", "--include-all",
         "--config", str(SCB_CHECK_CONFIG), str(path)],
        capture_output=True, text=True, cwd=CACHE_DIR)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"scb_check_error": (proc.stderr or proc.stdout)[-300:]}
    return {k: data.get(k) for k in SCB_KEYS}


def measure(root: Path, extra_excludes: tuple[str, ...] = ()) -> dict:
    files = code_files(root, extra_excludes)
    out: dict = {"code_files": len(files), "stmts": _stmts(files), "test_loc": test_loc(root)}
    if not files:
        return out
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="measure-", dir=CACHE_DIR) as tmp:
        scratch = Path(tmp) / "code"
        for rel, src in files.items():
            dest = scratch / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src)
        subprocess.run(["uvx", "-q", f"ruff=={RUFF_VERSION}", "format", "--isolated",
                        "--no-cache", "--line-length", "88", str(scratch)],
                       capture_output=True, cwd=CACHE_DIR)
        out.update(_scb_check(scratch))
    return out


def _ratio(num, den, min_den):
    if num is None or den is None or den < min_den:
        return None
    return round(num / den, 4)


def marginal(prev: dict, cur: dict) -> dict:
    """What the agent added, in scb-check's own units (None when the change is too small)."""
    def d(key):
        a, b = prev.get(key), cur.get(key)
        return None if a is None or b is None else b - a
    d_loc, d_mass = d("total_loc"), d("total_mass")
    return {
        "d_loc": d_loc, "d_stmts": d("stmts"), "d_flagged_loc": d("verbosity_flagged_loc"),
        "d_clone_loc": d("clone_loc"), "d_high_cc_functions": d("high_cc_functions"),
        "d_verbosity": None if d("verbosity") is None else round(d("verbosity"), 4),
        "d_erosion": None if d("erosion") is None else round(d("erosion"), 4),
        # share of *newly added* lines that are flagged/cloned (needs >= 20 net new lines)
        "marginal_verbosity": _ratio(d("verbosity_flagged_loc"), d_loc, 20),
        # share of *newly added* complexity mass that sits in CC>10 functions
        "marginal_erosion": _ratio(d("high_cc_mass"), d_mass, 1.0),
    }


def churn(prev_root: Path, cur_root: Path, extra_excludes: tuple[str, ...] = ()) -> dict:
    a, b = code_files(prev_root, extra_excludes), code_files(cur_root, extra_excludes)
    added = removed = 0
    for name in set(a) | set(b):
        for line in difflib.unified_diff(a.get(name, "").splitlines(), b.get(name, "").splitlines(),
                                         lineterm="", n=0):
            if line.startswith("+") and not line.startswith("+++"):
                added += bool(line[1:].strip())
            elif line.startswith("-") and not line.startswith("---"):
                removed += bool(line[1:].strip())
    return {"lines_added": added, "lines_removed": removed,
            "files_added": len(set(b) - set(a)), "files_removed": len(set(a) - set(b)),
            "files_changed": sum(1 for n in set(a) & set(b) if a[n] != b[n])}


def copy_snapshot(src: Path, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(
        ".venv", "venv", "__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache", ".mypy_cache"),
        symlinks=True)
