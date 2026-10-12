# Code Sloppiness × Context: an audit, and a research plan

*Prepared 5 Oct 2026. Source post: [“Measuring the Sloppiness of Code”, Earendil, 10 Sep 2026](https://earendil.com/posts/measuring-code-sloppiness/).*
*Everything marked **[pilot]** was measured locally. The script is `pilot/measure.py` and the raw numbers are in `pilot/results.json`.*

---

## 0. TL;DR

1. **The post is a short opinion piece built on one benchmark, SlopCodeBench (SCB; arXiv 2603.24755).** Its figures (verbosity 0.15 vs 0.33, erosion 0.31 vs 0.68) come from SCB **v1** (48 repos). SCB **v2** (May 2026, 473 repos) reports 0.19 vs 0.44 and 0.34 vs 0.68. The ~2× headline still holds.
2. **SCB never varies context.** It wipes the conversation between checkpoints and changes only the *instruction prompt*. Its main mitigation finding is that prompts move the starting level of slop but not its growth rate (“intercept, not slope”). So the post's claim that agents can't handle slop themselves rests on prompts alone. Memory, foresight, codebase context, context load, compaction and in-loop quality feedback were never tested. **That gap is your project.** The SCB authors call it out themselves: “interventions that enforce structural discipline across checkpoints … remain untested.”
3. **The metrics have measurement problems you must design around [pilot]:**
   - **Tool version:** on identical Flask code, `scb-check` verbosity reads 0.178 (v0.1.0), 0.228 (v0.1.3) and 0.178 (v0.2.0). That swing of about 0.05 is half the anti-slop prompt's effect on GPT‑5.4.
   - **Formatting:** the same code (3,145 AST statements, unchanged) reformatted at line length 60 vs 200 gives LOC +44%, clone lines **2.7×**, and verbosity 0.235 vs 0.205. Erosion is stable. The post's favourite metric, ΔLOC, is the most format-fragile one.
   - **Reproduction:** I could not reproduce the paper's Flask numbers (0.111 / 0.209) under any tool version or scope. I measured 0.178–0.235 / 0.237–0.289.
   - **Reference solutions:** SCB's own reference solutions (at least partly Codex-written) score **0.43 ± 0.16 verbosity and 0.62 ± 0.20 erosion** at the final checkpoint. That is the paper's *agent* range. Their metrics rise in **78% (erosion) and 83% (verbosity)** of the 36 trajectories, against 77% / 75.5% for agents in the paper. Growing specs plus floor effects (8 of 36 first checkpoints have erosion exactly 0) make “rises” close to inevitable. No human-written baseline on the same tasks exists.
   - **Predictive validity:** SCB's own sensitivity table (App. B.3) gives erosion a correlation of ≈0 (−0.018) with next-checkpoint pass rate. Plain LOC does better (−0.21 vs pass, +0.50 vs cost). This is the only quantitative support for the post's “ΔLOC works surprisingly well” remark.
4. **The recommended project:** a context-manipulation study on top of SCB's open harness, using **pi** as the agent. Pi is already a supported SCB agent, has a minimal system prompt, and exposes `--session`, `--no-context-files` and compaction controls. The headline experiment is **E3, “codebase-as-context”** (does sloppy existing code cause sloppier new code?). It is causal, cheap (one checkpoint per run) and new.
   - Use a **maintainability probe** as the primary outcome: the cost for a fixed agent to make standard future changes. Static metrics become secondary measures, checked against the probe and against human ratings.
   - The pilot tier costs about **$200–350** in API spend.

---

## 1. What the post claims

| # | Claim in the post | Where it comes from |
|---|---|---|
| C1 | “LLMs have become almost perfect at generating code” | Assertion |
| C2 | A 1–10 LLM judge is “basically equivalent to a random number generator”; pairwise judges flip when solutions are renamed | Author's experience; links arXiv 2604.16790 |
| C3 | Human review is best but doesn't scale | Assertion |
| C4 | ΔLOC is “a surprisingly effective metric”, though Goodhart applies | Author's tests (no data shown) |
| C5 | Verbosity = \|AST-grep flagged ∪ clone lines\| / LOC; Erosion = share of CC·√SLOC mass in functions with CC > 10 | SCB §2.3 |
| C6 | Repos 0.15 ± 0.06 vs agents 0.33 ± 0.10 verbosity; 0.31 ± 0.17 vs 0.68 ± 0.20 erosion; “roughly twice” | SCB v1 Table 2 |
| C7 | The author's own vibe-coded projects reach verbosity 0.4 and erosion 0.75; a “notoriously vibey” project scored low | Unpublished |
| C8 | SCB wipes context between checkpoints; bad decisions accumulate; SOTA gets “0% strict solve rate” | SCB §2.2, §3.1 |
| C9 | Agents “can't really deal with the slop either” | Inferred from C8 |
| C10 | Future directions: coupling, churn, cohesion | — |

## 2. Claim-by-claim audit

| # | Verdict | Notes |
|---|---|---|
| C1 | **Overstated, and contradicted by the cited source** | In SCB the best agent strictly passes 14.8% of checkpoints and 28.1% in isolation, and solves 0 of 36 problems end-to-end. “Almost perfect” only holds for single-shot tasks with full specs. |
| C2 | **Plausible, unquantified** | arXiv 2604.16790 shows code judges are highly prompt-sensitive, with biases big enough to reorder model rankings. The post gives no data of its own, and “random number generator” is rhetoric. SCB itself ships an LLM-judge rubric (`slop-code metrics judge`). |
| C3 | Agreed | Human panels are also noisy. Any human evaluation needs inter-rater reliability (e.g. Krippendorff's α) reported. |
| C4 | **Supported, with caveats** | SCB App. B.3: LOC correlates −0.212 with next-checkpoint pass and +0.502 with cost; erosion gets −0.018 / +0.167. **But** raw LOC moves ±44% with formatting alone **[pilot]** and grows ~4.5× across checkpoints even in reference solutions **[pilot]**. Normalise it by task: compare against a reference size, and count AST statements rather than physical lines. |
| C5 | Accurate restatement | Erosion has a hard threshold (CC > 10) and becomes unstable on small codebases. For example, xjq's 45-line reference solution has erosion 0.95, and 8 of 36 first-checkpoint references score exactly 0 **[pilot]**. The paper says 137 AST-grep rules; the published `scb-check` releases bundle 197 rule IDs. |
| C6 | **Stale, and over-read** | These are v1 numbers; v2 reports 0.19 ± 0.11 / 0.44 ± 0.18 and 0.34 ± 0.22 / 0.68 ± 0.20. The ± values are SDs, so the erosion distributions overlap heavily. The repos are not matched to the tasks: up to 2M-LOC libraries are compared with 0.1–8k-LOC CLI programs. SCB v1 itself says “This is not a matched human-solution baseline.” |
| C7 | Unverifiable | No sample size, tool version or scope. Footnote 4 admits a known false negative, which is itself evidence against construct validity. |
| C8 | **Mostly accurate, one terminology slip** | Context is wiped (“we do not provide the prior conversation's context”). The 0% figure is problems fully solved end-to-end. SCB's “strict solve rate” is a per-checkpoint metric that reaches 14.8%. |
| C9 | **Overreach** | SCB tested 3 prompts, mainly on 3 GPT models (plus one MiniMax anti-slop run in its Table 8). It never tested context carry-over, design-note memory, foresight, quality feedback in the loop, refactoring checkpoints, or tooling. The anti-slop prompt mostly restates the metric's own rule families (see §3.4), so even its gains may partly be the agent learning the metric. |
| C10 | Good direction | SCB's codebase already computes import-graph entropy (`metrics/languages/python/graph.py`). Coupling and churn are nearly free to add. |

## 3. Pilot measurements [pilot]

Reproduce with `uv run python pilot/measure.py` (needs git and uv; no API keys, no Docker). Pinned inputs: Flask `d73fa1c`, scb-problems `38d627e`, slop-code-bench `31ceea3`, ruff 0.16.10.

### 3.1 P1: tool version drift (identical code)

| `scb-check` | Flask/src verbosity | erosion | flagged lines |
|---|---|---|---|
| 0.1.0 | 0.178 | 0.284 | 749 |
| **0.1.3** (pinned by the SCB harness) | **0.228** | 0.284 | 956 |
| 0.2.0 (latest) | 0.178 | 0.289 | 749 |
| *Paper v2 value* | *0.111* | *0.209* | — |

- The SCB maintainers say so themselves in `metrics/checkpoint/driver.py`: “its rule set changes between releases, so an unpinned `uvx` invocation makes verbosity incomparable across runs.”
- The public leaderboard disagrees with the paper's tables. For example, GPT‑5.5 verbosity is 0.269 on the site and 0.32 in Table 1.
- Other variants also failed to reproduce the paper: Flask at the 2026‑03‑24 commit gave 0.227 / 0.284, and the full repo gave 0.200 / 0.237.
- **Implication:** pin one version and report a version-sensitivity check. Only ever compare numbers produced by the same tool version.

### 3.2 P2: formatting sensitivity (identical AST, 3,145 statements)

| ruff line length | LOC | clone lines | verbosity | erosion |
|---|---|---|---|---|
| 60 | 5,448 | 477 | 0.235 | 0.278 |
| 88 | 4,200 | 263 | 0.228 | 0.284 |
| 200 | 3,771 | 177 | 0.205 | 0.279 |

**Implication:** run a canonical formatter before measuring anything. Different models format differently, so without this step formatting style is mistaken for sloppiness. Measure size as AST statements, not physical lines.

### 3.3 P3: SCB reference solutions (36 problems, canonical protocol)

| | verbosity | erosion |
|---|---|---|
| Reference, first checkpoint | 0.323 ± 0.148 | 0.415 ± 0.294 |
| Reference, last checkpoint | **0.427 ± 0.163** | **0.623 ± 0.195** |
| Paper v2: human repos (HEAD) | 0.19 ± 0.11 | 0.34 ± 0.22 |
| Paper v2: agent checkpoints | 0.44 ± 0.18 | 0.68 ± 0.20 |

- Share of trajectories where the metric rises, first → last: erosion **28/36 (78%)**, verbosity **30/36 (83%)**. The paper reports 77% / 75.5% for agents and 53% / 68% for human repos.
- **Caveat:** the authorship of the reference solutions is undocumented. At least some are Codex-written (e.g. `__codex_row_number` in `file_query_tool`). So this probe *does not* show that humans write equally sloppy code.
- **What it does show:**
  - There is no human-written baseline on the same tasks.
  - “X% of trajectories rise” is not a diagnostic statistic: the benchmark's own reference path produces the same rate.
  - Absolute levels depend on the task. CLI and interpreter tasks have high cyclomatic complexity by nature.
- **Implication for your project:** compare arms on the same task, model and seed. Never compare agents with GitHub repos.

### 3.3b P4: `scb-check` reads config from the working directory

`scb-check` looks for `scb-check.toml`, or a `pyproject.toml` with a `[tool.ruff]` / `[tool.scb-check]` table, starting from the **current working directory** and walking up to the nearest `.git`. It applies any `exclude` / `extend-exclude` it finds there.

The same code can therefore score differently, or not at all, depending on where the tool is run. Run from inside the `scb-problems` checkout, whose `pyproject.toml` excludes `**/solutions/**`, it reports "no Python files found" for the reference solutions.

The harness always passes `--config configs/scb-check.toml` and runs from a neutral directory.

### 3.4 The anti-slop prompt overlaps the metric

The bullets in SCB's `anti_slop` prompt map almost one-to-one onto `scb-check` rule families:

| Prompt says | Matching rule IDs |
|---|---|
| “Extra defensive checks or try/catch blocks” | `defensive-*` |
| “Casts to get around type checking” | `pointless-bool-cast` |
| “Trivial wrappers” | `identity-wrapper-function` |
| “Heavy nesting” | `nested-*` |
| “If/Else ladders” | `*-ladder` |

Its large erosion and verbosity gains are therefore partly an effect of telling the agent what the metric checks. Any instruction-context experiment needs **held-out outcomes** that the instructions don't target.

---

## 4. What's already known about context and code quality

| Strand | Key result | What it leaves open for you |
|---|---|---|
| **AGENTS.md / context files**: 2602.11988 (*Evaluating AGENTS.md*), 2607.27250 (*Two-agent ablation*), 2601.20404 (*Efficiency*), 2511.12884 (*Agent READMEs*, 2,303 files) | Context files don't improve task success and add >20% cost (2602.11988). Context strategy moves correctness by ≤10–15 pp (2607.27250). They do cut runtime by 29% (2601.20404). Agents follow the instructions well, but repository overviews don't help. | **All of these measure correctness or cost. None measures code quality.** The obvious use of context files (style and architecture) has never been evaluated on quality. |
| **Multi-turn degradation**: 2505.06120 (*LLMs Get Lost in Multi-Turn Conversation*) | Average drop of 39% from single-turn to multi-turn, mostly from unreliability. Models commit to early assumptions and “do not recover”. | Predicts that **persistent context could make slop worse** through anchoring. That's a two-sided hypothesis worth testing. |
| **Emergent specifications**: 2603.17104 (SLUMP) | Single-shot specs beat progressively disclosed ones on 16/20 (Claude Code) and 14/20 (Codex) papers. **ProjectGuard**, an external project-state layer, recovers 90% of the faithfulness gap. | Faithfulness was measured, not sloppiness. Does structured persistent state also reduce slop? |
| **Continuous evolution**: 2603.13428 (SWE-Milestone, ex-EvoClaw), 2603.03823 (SWE-CI) | Pass rates fall from >80% on isolated tasks to 38% under continuity. | Pass/fail only. Brownfield repos, so these are candidates for a later generalisation arm. |
| **Compaction**: 2606.22528 (*Governance Decay*), 2608.01326, 2605.08580 | Compaction silently drops constraints the agent obeyed while they were visible. | Predicts that **style and architecture constraints decay after compaction**. Testable as an interrupted time series. |
| **Long-context degradation**: *Lost in the Middle* (Liu et al. 2023, 2307.03172); Chroma's “Context Rot” report (2025) | Retrieval and reasoning get worse as input grows and with position. | Not measured on code quality. Calls for a dose-response experiment. |
| **Interaction smells**: 2603.09701 | Taxonomy of multi-turn human–LLM coding failures. | Qualitative only. |
| **LLM-as-judge**: 2604.16790 | Judges are prompt- and position-biased. | Report bias sensitivity if you use a judge at all. |

---

## 5. Research design

### 5.1 Main question

> **How much does what's in the agent's context (memory of past work, knowledge of future needs, existing code, instructions, sheer volume, and compaction) change how sloppy its code is, and does it change the starting level, the growth rate, or both?**

Report two quantities for every manipulation:
- **Level:** sloppiness at the first checkpoint.
- **Slope:** sloppiness added per checkpoint.

SCB's prompt result was “level, not slope”, so the slope is where new findings are most likely.

### 5.2 A breakdown of “context” into things you can manipulate

| Dimension | What varies | Arms |
|---|---|---|
| **D1 Memory of prior work** | What the agent remembers from earlier checkpoints | `fresh` (SCB default) · `persistent` (full session carried over) · `compacted` (summary only) · `notes` (fresh context, but the agent keeps a `DESIGN.md`) |
| **D2 Foresight** | How much of the future spec the agent sees | `current-only` · `roadmap` (all future checkpoints visible, marked “don't build yet”) · `single-shot` (SCB `one_shot` mode, an upper bound) |
| **D3 Codebase as context** | Quality of the code the agent extends | `clean` · `reference` · `slopified`, all functionally equivalent and test-verified |
| **D4 Instructions** | Normative context (AGENTS.md) | `none` · `generic-best-practice` (not aligned to the metric) · `anti-slop` (SCB's, aligned to the metric) · `exemplar` (shows house style with code) · `architecture-doc` |
| **D5 Context load** | Volume and relevance of other tokens | Pre-fill of 0 / 32k / 64k / 128k tokens × {irrelevant, stale-relevant} |
| **D6 Compaction** | Lossy summarisation partway through a task | `off` (large window) · `default` · `aggressive` (low threshold) |
| **D7 Quality feedback** | Metric report shown between checkpoints | `none` · `scb-check report` · `probe feedback` (high Goodhart risk; treat as exploratory) |

### 5.3 Experiments, in priority order

**E0: Validate the measurements first. Required, and costs nothing in API spend.**
- Fix the measurement protocol: drop tests and venvs → `ruff format` (pinned) → `scb-check` pinned → size in AST statements. `pilot/measure.py::canonical_measure` already does this.
- **Test–retest:** run the same model and prompt with ≥5 seeds on 3 problems to get noise floors for each metric.
- **Convergent validity:** collect ~150 blinded pairwise human judgements (3 raters, report α). Check them against verbosity, erosion, the probe and an LLM judge (with position and label swapped).
- Exit criterion: know each metric's noise floor and how well it agrees with humans before trusting any effect.

**E1: Memory (D1) × Foresight (D2). Core trajectory study.**
- Arms: `fresh`, `persistent`, `compacted`, `notes`, `roadmap`, `single-shot`.
- **H1a:** `persistent` and `notes` lower the slope, because design intent is kept.
- **H1b (rival hypothesis):** `persistent` raises the slope through anchoring and context rot (2505.06120).
- **H1c:** `roadmap` lowers the level and the slope more than any memory arm. If so, slop is mostly *myopia*, not forgetting.
- Watch the cost confound: `persistent` uses far more tokens. Report quality per dollar and include a token-matched `fresh` arm that adds extra exploration turns.

**E2: Instruction context (D4) with Goodhart controls.**
- Same trajectory setup as E1, varying the AGENTS.md content. Load it through pi so `--no-context-files` controls the `none` arm.
- Primary outcomes must include measures *not* targeted by any instruction: the probe, coupling, dead code and human ratings.
- **H2:** metric-aligned instructions improve the targeted metrics more than the held-out ones, which would mean the agent is learning the metric. Exemplars beat rules (cf. “show, don't tell”, Bohr 2025, cited in SCB).

**E3: Codebase as context (D3). The flagship experiment: causal, cheap, new.**
- For each problem, pick a middle checkpoint *k*. Build three test-equivalent workspaces from the reference solution:
  - **clean:** refactored, test-verified, and human-reviewed.
  - **reference:** as-is.
  - **slopified:** deterministic transformations that keep behaviour. Inline helpers, duplicate blocks, add redundant guards and single-use variables, merge functions into a god function. Use 2 dose levels and re-run the full test suite.
- A fresh-context agent then implements checkpoint *k+1* in each workspace.
- **Measure only the code the agent adds or changes** (diff-scoped metrics), so the outcome isn't inflated by the inherited code.
- **H3:** agents copy local style, so sloppy code produces sloppier additions. If true, the main mechanism behind SCB's slope is the agent's *own earlier output acting as context*. The fix would then be periodic cleanup of that context (refactor checkpoints), not better prompts.
- Avoid circularity: “clean” must also be clean on held-out measures (human rating, probe), not just on `scb-check`.

**E4: Context load dose-response (D5).**
- Single-checkpoint runs, pre-filled through a seeded session file or `--append-system-prompt`.
- **H4:** quality falls as load rises, more steeply for stale-but-relevant text (old code and specs) than for irrelevant text.

**E5: Compaction (D6).**
- Log every compaction event in the `persistent` arm.
- Run an interrupted time series on edit quality before vs after each event, and manipulate the thresholds through pi `compaction.*` settings.
- **H5:** style and architecture conventions decay after compaction, similar to governance decay (2606.22528).

**E6 (exploratory): Quality feedback in the loop (D7).** Measures how far context-based feedback can push the slope, and how easily it gets gamed.

### 5.4 Outcomes

**Primary: Maintainability Probe Cost (MPC).**
- After the last checkpoint, a **fixed** probe agent (fixed model, pi version, prompt and fresh context; 3 seeds) attempts K≈3 hidden standard change requests per problem.
- Examples: add an output format, rename a domain concept everywhere, fix an injected bug.
- Record success, tokens, wall time and diff size.
- This defines sloppiness as “the cost it imposes on the next change”, which is what people actually care about. It also anchors static metrics to an outcome they should predict, which SCB never did.

**Secondary (all on canonicalised code, pinned tools):**
- verbosity and erosion, both snapshot and diff-scoped
- **bloat ratio**: agent AST statements ÷ reference AST statements at the same checkpoint
- ΔLOC per newly passing test
- churn (lines rewritten per checkpoint)
- clone ratio
- cognitive complexity
- coupling and instability (import graph)
- dead code (`vulture`)
- type errors (`pyright`)
- correctness: strict, isolated and core pass rates
- cost

**Validity anchors:**
- blinded pairwise human ratings on a stratified sample
- LLM judge with position/label swaps and repeated sampling, reporting its bias sensitivity as 2604.16790 recommends

### 5.5 Analysis

- **Model:** mixed effects, `y ~ arm * progress + (1 + progress | problem) + (1 | model:seed)`. Progress is normalised 0→1, using SCB's Start/Early/Mid/Late/Final phases for plots. The `arm` term is the level effect and `arm:progress` is the slope effect.
- **Attrition:** SCB leaves crashed checkpoints out of its quality metrics. Arms with different crash rates will bias the comparison, so report crash rates by arm. Run two analyses: everything, and only checkpoints that pass in isolation (since slop is cheap if the code is wrong anyway).
- **Correctness trade-off:** report Pareto fronts of quality against strict pass rate. SCB's anti-slop prompt cost 2.4 pp of strict pass rate.
- **Preregistration:** primary outcome = MPC plus diff-scoped verbosity and erosion; primary contrasts = E1 `persistent` vs `fresh`, E1 `roadmap` vs `fresh`, and E3 `slopified` vs `clean`. Correct for multiple comparisons (Holm) within each experiment.
- **Power (placeholder until E0 gives real variance):** SCB's effects range from ~0.05 (tool noise) to 0.09–0.15 (anti-slop on verbosity). For a 0.05 difference with paired SD ≈ 0.08: n ≈ ((1.96 + 0.84) × 0.08 / 0.05)² ≈ **20 paired trajectories per contrast**. That means about 7 problems × 3 seeds per model.

### 5.6 Infrastructure

Base everything on **SprocketLab/slop-code-bench** (MIT licence, 36 problems / 196 checkpoints, Docker, already supports `pi`).

| Need | Where | Change |
|---|---|---|
| Context carry-over | `src/slop_code/agent_runner/runner.py:662` hardcodes `finish_checkpoint(reset_context=True)` | Add a `context_mode` run setting (`fresh`, `persistent`, `compacted`, `notes`) |
| pi session persistence | `agents/pi/agent.py::_build_command` always passes `--no-session` | In `persistent` mode use `--session <host-mounted>/session.jsonl`; each checkpoint gets a fresh container, so the session file must live on the host |
| `compacted` | pi RPC `{"type":"compact","customInstructions":…}` | Run at checkpoint end, then continue the session |
| Compaction dose | pi settings `compaction.enabled / reserveTokens / keepRecentTokens` | Put these in pi's agent directory, **not** the workspace, so the agent can't see them |
| Roadmap | `get_task_for_checkpoint` renders a Jinja template with `spec` | New template with a `future_specs` variable |
| Single-shot | already there: `one_shot.enabled` (`configs/runs/single_shot.yaml`) | — |
| Instruction arms | pi `--no-context-files` / AGENTS.md in the workspace | Leave AGENTS.md out of the metrics (the metrics only read `.py` files) |
| Canonical metrics | `pilot/measure.py::canonical_measure` | Wrap into a post-processing step |
| Probe | New | Small driver: copy the final snapshot, run the fixed pi probe agent and the hidden tests |

**Why pi rather than Claude Code or Codex for the main arms:** vendor harnesses inject large, version-dependent system prompts and their own context-file logic. That hidden context confounds a study *about* context. Pi's prompt is small and every context source can be switched off. Run one vendor harness as an external-validity check.

**Pin everything and record it per run:** pi version, model snapshot ID, reasoning effort, `scb-check` 0.1.3, ruff 0.16.10, problem-repo commit.

### 5.7 Budget and timeline

Per-checkpoint costs from SCB Table 1: $0.20 (Spark) to $3.17 (Opus 4.6). Mid-tier models run $0.33–0.74. Persistent-context arms will probably cost 1.5–3× more, offset partly by prompt caching.

| Phase | Scope | Approx. API cost | Wall time |
|---|---|---|---|
| **0. Measurement validation** | E0: test–retest (3 problems × 5 seeds × 1 cheap model), human-rating calibration | ~$30–60 | Week 1 |
| **1. Pilot** | E1 on the SCB `lite` set (5 problems, 26 checkpoints) × {fresh, persistent, roadmap} × 3 seeds × 1 cheap model ≈ 234 checkpoints; E3 on 10 problems × 3 variants × 3 seeds = 90 runs | **~$200–350** | Week 2 |
| **2. Core** (preregistered) | E1 + E2: 12 problems (~65 checkpoints) × 6 arms × 2 models × 3 seeds ≈ 2.3k checkpoints; E3 full (36 × 3 × 3 × 2); E4 (288 single runs); MPC probe on all final codebases | ~$2.5–6k | Weeks 3–5; about 2 days of compute with 8 parallel containers |
| **3. Analysis & write-up** | Mixed models, human evaluation, robustness checks | Human time | Week 6 |

You can stop after Phase 1. E3 plus the pilot slice of E1 is already a publishable short paper or blog post.

### 5.8 Threats to validity

- **Construct:** static metrics are proxies, and the post admits a false negative (footnote 4). → MPC as the primary outcome, plus human anchoring.
- **Goodhart:** instructions aligned to the metric (§3.4), and feedback in the loop (E6). → Held-out outcomes.
- **Measurement artefacts:** tool version, formatting, small-codebase erosion. → Canonical protocol; report erosion only above a size floor (e.g. ≥300 AST statements) or use a smoothed, threshold-free variant.
- **Compute confound:** context arms use more tokens. → Report per dollar and include a token-matched control.
- **Contamination:** SCB problems are public and carry a canary GUID. → Write 2–3 private problems as a holdout.
- **Generalisation:** Python only, small greenfield CLI programs. → A later arm on brownfield repos (SWE-CI / SWE-Milestone tasks).
- **Model drift:** API models change silently. → Pin snapshots and finish each experiment within a short window.
- **Baseline validity:** no human solutions exist for these tasks. → Don't claim “agents vs humans”; claim “context arm A vs B”.

---

## 6. Next steps (in order)

1. Re-run `pilot/measure.py` to confirm the probes on your machine (~3 min).
2. Email the SCB authors (gorlanski@wisc.edu) about the Flask reproduction gap and the authorship of the reference solutions. Optionally email Sebastian at Earendil (sebastian@earendil.com); the post invites it, and pi is their harness.
3. Fork `slop-code-bench`, add `context_mode` and pi session persistence (§5.6), and test it on one problem.
4. Build the slopify/clean transformations for E3 (libcst, test-verified) on 3 problems.
5. Run Phase 0, then Phase 1. Preregister Phase 2 using the pilot variances.

## Appendix: sources

- Earendil, “Measuring the Sloppiness of Code” (10 Sep 2026).
- Orlanski et al., **SlopCodeBench**, arXiv 2603.24755 v1 (Mar 2026) / v2 (May 2026). Code: github.com/SprocketLab/slop-code-bench; problems: github.com/gabeorlanski/scb-problems; metrics: `scb-check` (PyPI 0.1.0–0.2.0).
- **Bias in the Loop: Auditing LLM-as-a-Judge for SE**, arXiv 2604.16790.
- **Evaluating AGENTS.md**, arXiv 2602.11988 · **Do Context Files Help Coding Agents?**, 2607.27250 · **Impact of AGENTS.md on Efficiency**, 2601.20404 · **Agent READMEs**, 2511.12884 · **Configuration Smells in AGENTS.md**, 2606.15828 · **Context Rot in AI-Assisted SD (config artefacts)**, 2606.09090.
- **LLMs Get Lost in Multi-Turn Conversation**, arXiv 2505.06120.
- **SLUMP: Faithfulness Loss Under Emergent Specification**, arXiv 2603.17104.
- **SWE-Milestone** (formerly EvoClaw), arXiv 2603.13428 · **SWE-CI**, arXiv 2603.03823.
- **Governance Decay (compaction)**, arXiv 2606.22528 · **Context Compaction Theory**, 2608.01326 · **Slipstream**, 2605.08580.
- **Interaction Smells in Multi-Turn Code Generation**, arXiv 2603.09701.
- Liu et al., **Lost in the Middle**, arXiv 2307.03172 · Chroma, **Context Rot** technical report (2025). These two are cited from memory and were not re-checked in this audit.
- McCabe, “A Complexity Measure”, IEEE TSE 1976.
