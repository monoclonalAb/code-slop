"""Pinned versions, paths and config loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS = REPO_ROOT / "configs"
ARMS_DIR = REPO_ROOT / "arms"
PROMPTS_DIR = REPO_ROOT / "prompts"
RUNS_DIR = REPO_ROOT / "runs"
# Caches and scratch live OUTSIDE any git repo / pyproject so tools don't pick up stray config.
CACHE_DIR = Path(os.environ.get("CODESLOP_CACHE", Path.home() / ".cache" / "codeslop"))

# ---- pins (record these with every result) ---------------------------------------------------
PI_VERSION = "1.0.4"
IMAGE = f"codeslop-agent:pi-{PI_VERSION}"
SCB_PROBLEMS_URL = "https://github.com/gabeorlanski/scb-problems"
SCB_PROBLEMS_COMMIT = "38d627ecf668a88f88f8d260f8df8df6116e9b03"
SCB_CHECK_VERSION = "0.1.3"  # same pin as slop-code-bench @ 31ceea3
RUFF_VERSION = "0.16.10"
SCB_CHECK_CONFIG = CONFIGS / "scb-check.toml"

PINS = {
    "pi": PI_VERSION,
    "image": IMAGE,
    "scb_problems_commit": SCB_PROBLEMS_COMMIT,
    "scb_check": SCB_CHECK_VERSION,
    "ruff": RUFF_VERSION,
}


@dataclass(frozen=True)
class ModelSpec:
    key: str
    provider: str
    id: str
    thinking: str = "high"


@dataclass(frozen=True)
class ProblemRun:
    name: str
    start: int  # seed workspace with reference solution at checkpoint_<start>
    max_checkpoints: int | None = None  # cap how many checkpoints after `start` to run


@dataclass
class Experiment:
    name: str
    models: list[str]
    arms: list[str]
    seeds: list[int]
    problems: list[ProblemRun]
    timeout_minutes: int = 60
    jobs: int = 1
    prompt: str = "just-solve.jinja"
    extra: dict = field(default_factory=dict)


def load_models() -> tuple[dict[str, ModelSpec], dict[str, dict]]:
    data = yaml.safe_load((CONFIGS / "models.yaml").read_text())
    models = {
        key: ModelSpec(key=key, provider=v["provider"], id=v["id"], thinking=v.get("thinking", "high"))
        for key, v in data["models"].items()
    }
    return models, data.get("providers", {})


def load_experiment(path: Path) -> Experiment:
    data = yaml.safe_load(path.read_text())
    problems = []
    for p in data["problems"]:
        if isinstance(p, str):
            p = {"name": p}
        problems.append(ProblemRun(name=p["name"], start=int(p.get("start", 1)),
                                   max_checkpoints=p.get("max_checkpoints")))
    known = {"name", "models", "arms", "seeds", "problems", "timeout_minutes", "jobs", "prompt"}
    return Experiment(
        name=data["name"],
        models=list(data["models"]),
        arms=list(data["arms"]),
        seeds=[int(s) for s in data.get("seeds", [0])],
        problems=problems,
        timeout_minutes=int(data.get("timeout_minutes", 60)),
        jobs=int(data.get("jobs", 1)),
        prompt=data.get("prompt", "just-solve.jinja"),
        extra={k: v for k, v in data.items() if k not in known},
    )
