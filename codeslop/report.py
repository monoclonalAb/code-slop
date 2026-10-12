"""Aggregate result.json files into results.csv and a model x arm summary table."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

SUMMARY_COLS = [
    ("n", None),
    ("iso", "eval_iso"),
    ("strict", "eval_strict"),
    ("pass%", "eval_pass_rate"),
    ("verb", "q_verbosity"),
    ("eros", "q_erosion"),
    ("m_verb", "step_marginal_verbosity"),
    ("m_eros", "step_marginal_erosion"),
    ("Δstmts", "step_d_stmts"),
    ("+lines", "churn_lines_added"),
    ("docs_rd", "agent_docs_reads"),
    ("$list", "agent_cost_usd_list_price"),
    ("min", "agent_wall_s"),
]


def load_rows(exp_dir: Path) -> list[dict]:
    rows = []
    for path in sorted(exp_dir.rglob("result.json")):
        row = json.loads(path.read_text())
        row.pop("pins", None)
        rows.append(row)
    return rows


def write_csv(rows: list[dict], path: Path) -> None:
    keys: list[str] = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in r.items()})


def _mean(values):
    xs = [float(v) for v in values if v is not None and v != ""]
    return statistics.mean(xs) if xs else None


def summary_table(rows: list[dict]) -> str:
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["arm"])].append(r)
    header = ["model", "arm"] + [c for c, _ in SUMMARY_COLS]
    lines = [header]
    for (model, arm), rs in sorted(groups.items()):
        cells = [model, arm]
        for name, key in SUMMARY_COLS:
            if key is None:
                cells.append(str(len(rs)))
                continue
            m = _mean([r.get(key) for r in rs])
            if m is None:
                cells.append("-")
            elif name == "min":
                cells.append(f"{m / 60:.1f}")
            elif name in ("iso", "strict", "pass%"):
                cells.append(f"{100 * m:.0f}")
            elif name in ("Δstmts", "+lines", "docs_rd"):
                cells.append(f"{m:.0f}")
            elif name == "$list":
                cells.append(f"{m:.2f}")
            else:
                cells.append(f"{m:.3f}")
        lines.append(cells)
    widths = [max(len(row[i]) for row in lines) for i in range(len(header))]
    out = ["  ".join(c.ljust(w) for c, w in zip(row, widths)) for row in lines]
    out.insert(1, "  ".join("-" * w for w in widths))
    legend = ("\niso/strict/pass% = checkpoint solved in isolation / incl. regressions / tests passed (%)"
              "\nverb/eros = snapshot verbosity/erosion; m_verb/m_eros = marginal (newly added code only;"
              "\n  m_eros > 1 means existing functions were pushed over the CC>10 threshold)"
              "\nΔstmts = AST statements added this checkpoint; docs_rd = explicit reads of docs/**"
              "\n$list = cost at API list price (subscription runs are not billed per token)")
    return "\n".join(out) + legend


def report(exp_dir: Path) -> str:
    rows = load_rows(exp_dir)
    if not rows:
        return f"no results under {exp_dir}"
    write_csv(rows, exp_dir / "results.csv")
    failed = sorted(p.parent.relative_to(exp_dir).as_posix() for p in exp_dir.rglob("FAILED"))
    text = summary_table(rows) + f"\n\nwrote {exp_dir / 'results.csv'} ({len(rows)} checkpoint rows)"
    if failed:
        text += f"\nFAILED trajectories ({len(failed)}): " + ", ".join(failed)
    return text
