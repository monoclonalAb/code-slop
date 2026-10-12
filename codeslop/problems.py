"""SlopCodeBench problems (pinned scb-problems checkout): specs, reference solutions, tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from codeslop.config import CACHE_DIR
from codeslop.config import SCB_PROBLEMS_COMMIT
from codeslop.config import SCB_PROBLEMS_URL

PROBLEMS_DIR = CACHE_DIR / "scb-problems"

_CANARY_HTML = re.compile(r"^<!-- [\s\S]+? -->\n?")
_ENTRY_FILE = re.compile(r"%%%ENTRYPOINT:entry_file%%%")
_ENTRY_CMD = re.compile(r"%%%ENTRYPOINT:entry_command%%%")


def ensure_problems_repo() -> Path:
    """Clone scb-problems at the pinned commit (idempotent)."""
    if not (PROBLEMS_DIR / ".git").exists():
        PROBLEMS_DIR.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", SCB_PROBLEMS_URL, str(PROBLEMS_DIR)], check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROBLEMS_DIR, capture_output=True,
                          text=True, check=True).stdout.strip()
    if head != SCB_PROBLEMS_COMMIT:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=PROBLEMS_DIR, check=True)
        subprocess.run(["git", "checkout", "-q", SCB_PROBLEMS_COMMIT], cwd=PROBLEMS_DIR, check=True)
    return PROBLEMS_DIR


@dataclass(frozen=True)
class Problem:
    name: str
    path: Path
    entry_file: str  # without .py
    checkpoints: tuple[str, ...]  # ordered names, e.g. ("checkpoint_1", ...)
    static_assets: tuple[tuple[str, str, Path], ...]  # (name, workspace save path, abs source)
    test_dependencies: tuple[str, ...]
    timeout: int

    @property
    def asset_paths(self) -> tuple[str, ...]:
        """Workspace-relative static asset paths (excluded from code metrics)."""
        return tuple(save for _name, save, _src in self.static_assets)

    @property
    def entry_py(self) -> str:
        return f"{self.entry_file}.py"

    def checkpoint_index(self, name: str) -> int:
        return self.checkpoints.index(name) + 1

    def solution_dir(self, n: int) -> Path:
        return self.path / "solutions" / f"checkpoint_{n}"

    def spec(self, checkpoint: str, *, agent: bool = True) -> str:
        """Checkpoint spec with canary stripped and entrypoint placeholders filled (as SCB does)."""
        text = (self.path / f"{checkpoint}.md").read_text()
        text = _CANARY_HTML.sub("", text)
        text = _ENTRY_FILE.sub(self.entry_py, text)
        command = f"python {self.entry_py}" if agent else f"uv run {self.entry_py}"
        return _ENTRY_CMD.sub(command, text)


@cache
def load_problem(name: str) -> Problem:
    root = ensure_problems_repo() / name
    cfg = yaml.safe_load((root / "config.yaml").read_text())
    cps = sorted(cfg["checkpoints"].items(), key=lambda kv: kv[1].get("order", 0))
    assets = []
    for key, spec in (cfg.get("static_assets") or {}).items():
        src = root / spec["path"]
        save = spec.get("save_path") or spec["path"]
        assets.append((key, save, src))
    return Problem(
        name=name,
        path=root,
        entry_file=cfg["entry_file"],
        checkpoints=tuple(name for name, _ in cps),
        static_assets=tuple(assets),
        test_dependencies=tuple(cfg.get("test_dependencies") or ()),
        timeout=int(cfg.get("timeout", 30)),
    )


def list_problems() -> list[str]:
    root = ensure_problems_repo()
    return sorted(p.name for p in root.iterdir() if (p / "config.yaml").exists())


SEED_IGNORE = shutil.ignore_patterns("tests", "__pycache__", ".venv", "*.pyc", ".pytest_cache")


def seed_workspace(problem: Problem, start: int, dest: Path) -> None:
    """Workspace = reference solution at checkpoint_<start> (minus its tests) + static assets."""
    src = problem.solution_dir(start)
    if not src.is_dir():
        raise FileNotFoundError(f"{problem.name}: no reference solution for checkpoint_{start}")
    shutil.copytree(src, dest, ignore=SEED_IGNORE, dirs_exist_ok=True)
    for _name, save, asset_src in problem.static_assets:
        target = dest / save
        if asset_src.is_dir():
            shutil.copytree(asset_src, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(asset_src, target)
