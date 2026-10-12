# Arms (context conditions)

Each trajectory starts from the SlopCodeBench reference solution at `checkpoint_<start>` and asks
the agent to implement the later checkpoints. Arms differ **only** in the context files present
in the workspace when each checkpoint starts.

| arm | AGENTS.md | docs/ | between checkpoints |
|---|---|---|---|
| `none` | – | – | any context file the agent wrote is removed |
| `generic` | `generic/AGENTS.md` (same for every problem) | – | restored |
| `autogen` | written by the model under test with an `/init`-style prompt (`prompts/init.jinja`) | – | restored |
| `good` | `good/<problem>/AGENTS.md` | – | restored |
| `good_docs` | `good` + `_shared/docs_pointer.md` | `good_docs/<problem>/docs/` | restored, so docs go stale as the code moves on |
| `good_docs_maintained` | `good_docs` + `_shared/maintenance.md` | same | the agent's edits persist |

`good` vs `good_docs` differ only by the docs pointer plus `docs/`, so that contrast isolates the effect of `docs/`.

## Directory layout

```
arms/
  generic/AGENTS.md
  _shared/docs_pointer.md
  _shared/maintenance.md
  good/<problem>/AGENTS.md
  good_docs/<problem>/docs/*.md
```

`codeslop run` refuses to start if an arm's material is missing for any problem in the experiment.

## Rules for writing `good` / `good_docs` material

These rules keep the treatment honest. Check every new problem against them.

1. **No foresight.** Describe only the code at `checkpoint_<start>` and the specs up to and including that checkpoint. Never read later `checkpoint_N.md` files or later reference solutions while writing. Docs must not hint at features that don't exist yet.
2. **Don't teach the metric.** Don't paste `scb-check` rule names or list its anti-patterns ("avoid single-use variables", "no isinstance ladders", …). Write what a strong maintainer would actually tell a new contributor: concrete structure, conventions, extension points, pitfalls *for this codebase*. General design guidance phrased as this project's conventions is fine.
3. **Be accurate.** Every path, name and command must match the seed workspace. Test commands by hand where possible.
4. **Same author and style across problems.** Record who wrote each file (human, model + human review, …) in the table below. Authorship is a variable.
5. **Size budget:** `good` AGENTS.md around 60–120 lines; `docs/` around 150–300 lines in total.

## Authored material

| problem | start | good | good_docs | author | reviewed |
|---|---|---|---|---|---|
| file_backup | 2 | ✓ | ✓ | Claude (pi session, Oct 2026); worked example | **needs human review** |
