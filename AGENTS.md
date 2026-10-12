# code-slop agent notes

Where things live, how to keep changes honest, and the rule that applies after
every change. Human-facing introduction: [README.md](README.md).

## Before changing anything

1. Run `git status --short`; preserve unrelated and pre-existing working-tree edits.
2. Read [README.md](README.md) (design, quickstart, pins) and, before design
   changes, [AUDIT.md](AUDIT.md) (background audit and research plan).
3. When touching arm material, read [arms/README.md](arms/README.md) and follow
   its rules: no foresight past the start checkpoint, never teach the metric,
   accuracy, one author and style across problems.

## Working rules

- Treat the pins in README.md (pi, scb-problems, scb-check, ruff) and the
  experiment design in AUDIT.md as fixed; do not relitigate them unasked.
- Keep secrets out of repo files: only host logins are copied into containers,
  and runs/ is gitignored.
- Match verification to the change: `uv run codeslop doctor`, a smoke run or
  `verify-reference` beat reasoning; say what you ran and what you skipped.
- After a change, update the docs it invalidates (README.md, AUDIT.md,
  arms/README.md) in the same change.

## Pre-completion audit (owner rule)

After every change that touched files, before reporting the task complete:

1. Finish the work first, including checks and doc updates, so the audit sees
   the final diff.
2. Run `bash scripts/audit-changes.sh "<one or two sentences on what the task
   asked for>"`, allowing about 20 minutes (bash timeout 1200 s). GPT-6 Astra
   (`openai-codex/gpt-6-astra`) at `xhigh` reviews the changes read-only, with
   only read, grep, find and ls. Add `--base <ref>` when the task's work is
   already committed.
3. Check each finding against the code, fix the real ones, and rerun the checks
   those fixes touch. If the fixes were more than small corrections, run the
   audit once more.
4. In the final report, say what was fixed and what was rejected, and why.

Exit codes: 0 `VERDICT: PASS`, 3 findings to handle, 1 audit failed or gave no
verdict (retry once, then report the audit as skipped), 2 usage. `--dry-run`
prints what would be sent without calling the model. The diff goes to OpenAI
through the owner's Codex login, so never run the audit while changed or
untracked files hold secrets or production data.