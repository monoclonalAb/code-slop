# code-slop

**Does a good `AGENTS.md` + `docs/` setup make coding agents write less sloppy code?**

Built on [SlopCodeBench](https://arxiv.org/abs/2603.24755): its problems, hidden tests and quality metrics (verbosity, erosion). Agents are run through [pi](https://pi.dev) inside Docker using the latest Anthropic and OpenAI models. See [`AUDIT.md`](AUDIT.md) for the background audit and why the design looks like this.

## Design in one paragraph

Each trajectory starts *brownfield*: the workspace is the SlopCodeBench reference solution at checkpoint *k*. The agent then implements checkpoints *k+1…n* in order, building on its own code, with a fresh pi context per checkpoint (as in SlopCodeBench). The only thing that varies between **arms** is the context in the workspace when each checkpoint starts:

- `none`
- `generic` boilerplate AGENTS.md
- `autogen` (the model writes its own AGENTS.md, `/init`-style)
- `good` (curated AGENTS.md)
- `good_docs` (`good` + a `docs/` folder)
- `good_docs_maintained` (the agent must keep the docs current)

Details: [`arms/README.md`](arms/README.md). After every checkpoint we record:

- hidden-test results (strict / isolated / core / regression)
- quality, measured canonically: snapshot verbosity/erosion, *marginal* verbosity/erosion of newly added code, AST statements added, churn
- cost and tokens
- whether the agent actually read `docs/`

## Quickstart

Requires Docker (OrbStack is fine), [uv](https://docs.astral.sh/uv/), and `pi` logged in (`pi` → `/login`).

```bash
uv sync
uv run codeslop doctor                       # docker, image, logins, pinned tools
uv run codeslop build-image                  # first time only (doctor tells you)
uv run codeslop doctor --live --models opus-5.5,gpt-6.1-sol   # tiny in-container canary

uv run codeslop verify-reference file_backup # eval pipeline sanity check: should be 100%, no LLM

uv run codeslop run configs/smoke.yaml       # 4 agent runs end-to-end
uv run codeslop run configs/pilot.yaml --dry-run
uv run codeslop run configs/pilot.yaml       # resumable: finished trajectories are skipped
uv run codeslop report runs/pilot            # summary table + runs/pilot/results.csv
```

Restrict a run with `--models gpt-6.1-sol --arms none,good_docs`.

## Models and auth

Models are listed in [`configs/models.yaml`](configs/models.yaml).

| Provider | Models | Default |
|---|---|---|
| Anthropic | Opus 5.5, Sonnet 5.5, Fable 5.1 | Opus 5.5 |
| OpenAI | GPT‑6.1 Sol, GPT‑6 Astra, GPT‑6 Luna | GPT‑6.1 Sol |

- **OpenAI** runs on your ChatGPT/Codex plan through pi's `openai-codex` OAuth login.
- **Anthropic:** Claude subscriptions now bill third-party apps (including pi) against *extra usage*, not plan limits. Either enable extra usage at claude.ai/settings/usage, or `export ANTHROPIC_API_KEY=...`. `auth: auto` then uses the key, billed per token.
- OAuth tokens are copied into each container (one provider only) and refreshed on the host first, so containers never rotate your refresh token. The `$list` cost column is API list price, for comparison only.

## Adding problems

1. Pick a start checkpoint *k* (roughly the middle) and confirm `codeslop verify-reference <problem>` passes.
2. Write `arms/good/<problem>/AGENTS.md` and `arms/good_docs/<problem>/docs/`, following the rules in `arms/README.md`: no foresight (never read later checkpoints) and no metric-teaching.
3. Add the problem to `configs/pilot.yaml`.

## Layout

```
codeslop/   harness: problems, arms, agent (pi in docker), evaluate (hidden tests), metrics, runner, report
arms/       context material per arm (+ authoring rules)
configs/    models, experiments, scb-check config
prompts/    just-solve (SlopCodeBench's baseline prompt, verbatim), init (/init-style AGENTS.md)
docker/     agent + eval image (python 3.12, uv, node 24, pi pinned)
pilot/      measurement-validity probes from the audit
scripts/    pre-completion audit (Astra reviews a task's diff, see AGENTS.md)
AUDIT.md    audit of the Earendil post + SlopCodeBench, and the research plan
```

Pinned: pi 1.0.4 · scb-problems `38d627e` · scb-check 0.1.3 · ruff 0.16.10. Pins are recorded in every `result.json`.
