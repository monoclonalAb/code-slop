"""Context arms: which AGENTS.md / docs/ the agent sees at each checkpoint.

| arm                  | AGENTS.md                                   | docs/                      | between checkpoints  |
|----------------------|---------------------------------------------|----------------------------|----------------------|
| none                 | -                                           | -                          | agent-made context files removed |
| generic              | arms/generic/AGENTS.md (same for all)       | -                          | restored             |
| autogen              | written by the model under test (/init)     | -                          | restored             |
| good                 | arms/good/<problem>/AGENTS.md               | -                          | restored             |
| good_docs            | good + _shared/docs_pointer.md              | arms/good_docs/<problem>/docs | restored (docs go stale) |
| good_docs_maintained | good_docs + _shared/maintenance.md          | same as good_docs          | agent edits persist  |

good -> good_docs differs ONLY by the docs pointer + docs/ folder, so that contrast isolates docs/.
"Restored" keeps the treatment fixed: agent edits to context files during checkpoint i are undone
before checkpoint i+1 (edits are still detected and recorded per checkpoint).
"""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from codeslop.config import ARMS_DIR

CONTEXT_FILES = ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md")


@dataclass(frozen=True)
class Arm:
    name: str
    agents: str | None  # "generic" | "good" | "autogen" | None
    docs: bool = False  # copy arms/good_docs/<problem>/docs
    appends: tuple[str, ...] = ()  # files under arms/ appended to AGENTS.md
    maintained: bool = False

    @property
    def loads_context(self) -> bool:
        return self.agents is not None


ARMS: dict[str, Arm] = {
    "none": Arm("none", None),
    "generic": Arm("generic", "generic"),
    "autogen": Arm("autogen", "autogen"),
    "good": Arm("good", "good"),
    "good_docs": Arm("good_docs", "good", docs=True, appends=("_shared/docs_pointer.md",)),
    "good_docs_maintained": Arm("good_docs_maintained", "good", docs=True,
                                appends=("_shared/docs_pointer.md", "_shared/maintenance.md"),
                                maintained=True),
}


@dataclass(frozen=True)
class Material:
    agents_md: str | None
    docs_dir: Path | None


def material(arm: Arm, problem: str, autogen_agents_md: Path | None = None) -> Material:
    if arm.agents is None:
        return Material(None, None)
    if arm.agents == "autogen":
        if autogen_agents_md is None:
            raise ValueError("autogen arm needs a generated AGENTS.md")
        src = autogen_agents_md
    elif arm.agents == "generic":
        src = ARMS_DIR / "generic" / "AGENTS.md"
    else:
        src = ARMS_DIR / arm.agents / problem / "AGENTS.md"
    if not src.exists():
        raise FileNotFoundError(f"arm '{arm.name}': missing {src} (see arms/README.md)")
    text = src.read_text()
    for extra in arm.appends:
        text = text.rstrip() + "\n\n" + (ARMS_DIR / extra).read_text()
    docs = None
    if arm.docs:
        docs = ARMS_DIR / "good_docs" / problem / "docs"
        if not docs.is_dir():
            raise FileNotFoundError(f"arm '{arm.name}': missing {docs} (see arms/README.md)")
    return Material(text, docs)


def missing(arm_names: list[str], problems: list[str]) -> list[str]:
    errs = []
    for a in arm_names:
        if a not in ARMS:
            errs.append(f"unknown arm '{a}' (known: {', '.join(ARMS)})")
            continue
        if ARMS[a].agents == "autogen":
            continue
        for p in problems:
            try:
                material(ARMS[a], p)
            except FileNotFoundError as e:
                errs.append(str(e))
    return errs


def apply(arm: Arm, workspace: Path, mat: Material, *, first: bool) -> None:
    """Put the arm's context files in place before a checkpoint."""
    if arm.maintained and not first:
        return
    for name in CONTEXT_FILES:
        (workspace / name).unlink(missing_ok=True)
    if mat.docs_dir is not None:
        shutil.rmtree(workspace / "docs", ignore_errors=True)
        shutil.copytree(mat.docs_dir, workspace / "docs")
    if mat.agents_md is not None:
        (workspace / "AGENTS.md").write_text(mat.agents_md)


def context_fingerprint(workspace: Path) -> dict[str, str]:
    """Hashes of context files + docs/** (to record whether the agent edited them)."""
    out = {}
    for name in CONTEXT_FILES:
        p = workspace / name
        if p.exists():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    docs = workspace / "docs"
    if docs.is_dir():
        for p in sorted(docs.rglob("*")):
            if p.is_file():
                out[p.relative_to(workspace).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out
