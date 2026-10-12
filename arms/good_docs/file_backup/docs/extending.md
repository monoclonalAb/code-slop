# Extending the scheduler

Recipes for the common kinds of change. Each one keeps the module boundaries in [architecture.md](architecture.md) intact.

## Add a field to the schedule YAML

1. Add the field to the right dataclass in `scheduler/models.py`, with a default if it is optional.
2. Parse and validate it in `scheduler/parser.py` next to its siblings (`_parse_job`, `_parse_when` or `_parse_strategy`). Raise `ScheduleValidationError` with a message naming the field. Normalize here (defaults, types, resolved paths) so consumers never re-check.
3. Read it from the model in `scheduler/executor.py`. Do not look at raw YAML there.

If a new sub-object has more than a couple of fields, give it its own dataclass and its own `_parse_<thing>` function rather than inlining it into `_parse_job`.

## Add a new event

1. Emit it with `emit({...})` from the code that knows the fact, typically `run_job` or a strategy executor. Use `event` plus `job_id` first, then the event's own fields, matching the spec's required fields exactly.
2. Never print or serialize in library code. `EventEmitter` handles JSON.
3. Check ordering against the invariants in [architecture.md](architecture.md).

## Add a new strategy kind

1. Subclass `BaseStrategyExecutor` in `scheduler/executor.py`. If the executor gets large or needs helpers, put it in its own module under `scheduler/`.
2. Implement `kind` and `handle_file`. Override `finalize` and `completed_fields` only if needed.
3. Construct it in `_create_strategy_executor`.
4. Allow the kind, and validate its `options`, in `_parse_strategy`. Store parsed options on `JobStrategy`, adding fields there if needed.
5. `run_job` should not need to change. If it seems to, the new behaviour probably belongs in a hook.

## Add a new schedule kind (`when.kind`)

1. Extend `_parse_when` to accept and validate it, storing what you need on `JobWhen`.
2. Extend `_compute_due_locals`. Keep each kind's due-time logic in its own small function if the branch grows beyond a few lines.

## Add a CLI flag

Add it in `parse_args()`, validate it in `main()` next to the existing checks (bad values map to `E_SCHEMA`), and pass plain values into library functions. The scheduler package must not read `argparse` objects.

## Manual check

```bash
.venv/bin/python backup_scheduler.py --schedule /tmp/s.yaml --now 2025-09-10T03:30:00Z --mount files
```

Use a schedule that hits your change. Compare against the spec examples, including event order and the compact JSON format.
