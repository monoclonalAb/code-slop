# Backup scheduler: guide for coding agents

`backup_scheduler.py` is a CLI that reads a YAML schedule, works out which jobs are due in a time window, simulates running them, and writes an event history to stdout as compact JSON Lines.

## Run it

```bash
.venv/bin/python backup_scheduler.py \
  --schedule schedule.yaml --now 2025-09-10T03:30:00Z --duration 24 --mount files
```

- Dependencies are in `requirements.txt` (PyYAML). Use the existing `.venv`; add any new dependency to `requirements.txt`.
- `files/` is a small sample tree (the one used in the spec examples). Use it for manual runs.
- Errors go to stderr as `ERROR:<CODE>:<message>` with an exit code: `E_PARSE` → 3, `E_SCHEMA` → 4. Nothing else should be printed on error.

## Layout

| Path | Responsibility |
|---|---|
| `backup_scheduler.py` | CLI only: argument parsing, `--now` parsing, `--mount` resolution, mapping errors to exit codes, emitting `SCHEDULE_PARSED` / `JOB_ELIGIBLE`, calling `run_job`. |
| `scheduler/models.py` | Frozen dataclasses: `Schedule`, `Job`, `JobWhen`, `JobStrategy`. The only shape the rest of the code consumes. |
| `scheduler/parser.py` | YAML → models. **All** schema validation lives here and raises `ScheduleValidationError`. |
| `scheduler/executor.py` | Due-time evaluation, file walking, exclusion matching, `run_job`, and the strategy executors. |
| `scheduler/errors.py` | `ScheduleValidationError`. |

Data flow: `parse_args` → `load_schedule` (validate everything up front) → `evaluate_due_jobs` (due times per job) → for each job (sorted by id) and each due time: emit `JOB_ELIGIBLE`, then `run_job(job, emit, run_time=...)`.

## Conventions

- **Validate at the boundary, trust inside.** New config fields go through three places: a field on the right dataclass in `models.py`, parsing and validation in `parser.py`, use in `executor.py`. Raw YAML dicts never leave the parser. Executor code assumes valid models.
- **Events are dicts passed to `emit`.** Library code never prints. JSON serialization happens in one place, `EventEmitter` in the CLI.
- **Strategies are classes.** Strategy-specific behaviour belongs in a `BaseStrategyExecutor` subclass (`kind`, `handle_file`, `finalize`, `completed_fields`). `run_job` stays strategy-agnostic. A new strategy means a new subclass, a branch in `_create_strategy_executor`, and the kind added to `_parse_strategy`.
- **Determinism is part of the contract.** Jobs are sorted by id. Files are sorted lexicographically by relative POSIX path. Times are floored to the minute and formatted with `format_local_timestamp` (`Z` for UTC). Tar archives use fixed metadata (`_create_tar_archive`).
- **One home per concept.** Constants and helpers are defined once and imported. `DEFAULT_PACK_MAX_BYTES` is currently defined in both `parser.py` and `executor.py`; if you touch it, keep one definition.
- **Small, single-purpose functions.** When a function picks up a new responsibility, extract a function or class, or a new module under `scheduler/`, instead of growing `main()` or `run_job` with more branches.
- **Style:** `from __future__ import annotations`, type hints on every function, one import per line (`from x import y`), private helpers prefixed with `_`.

## Pitfalls

- A relative `--mount` resolves against the **schedule file's directory**, not the current directory.
- `once` timestamps are naive and interpreted in the schedule's timezone. Daily and weekly due times are computed per *local* date, so DST and timezone offsets matter.
- Exclusion uses the project's own `**`-aware matcher (`_pattern_matches`, fnmatch per path segment). It is case-sensitive and relative to the job's `source`. Do not swap in `pathlib.glob`; the semantics differ.
- YAML syntax errors are carried as `ScheduleValidationError("YAML:...")` and mapped to `E_PARSE` in the CLI. Every other validation error is `E_SCHEMA`.
- `FILE_EXCLUDED.pattern` is the **first** matching pattern in list order.

## Before you finish

Run the CLI against `files/` with a schedule that exercises your change, and compare the output with the spec's examples, field by field.
