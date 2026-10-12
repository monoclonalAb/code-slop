# Architecture

## One run, end to end

```
backup_scheduler.py main()
  ├─ parse_args()                        CLI flags
  ├─ _parse_now()                        --now → aware UTC datetime, floored to the minute
  ├─ resolve --mount                     relative paths resolve against the schedule's directory
  ├─ scheduler.parser.load_schedule()    YAML → Schedule (raises ScheduleValidationError)
  ├─ emit SCHEDULE_PARSED
  ├─ scheduler.executor.evaluate_due_jobs()   {job_id: [due local datetimes]}
  └─ for job in jobs sorted by id:
       for due_time in due_map[job_id]:
         emit JOB_ELIGIBLE
         scheduler.executor.run_job(job, emit, run_time=due_time)
            ├─ emit JOB_STARTED
            ├─ strategy executor = _create_strategy_executor(job, ...)   (None if no strategy)
            ├─ emit STRATEGY_SELECTED                                    (if strategy)
            ├─ for path in iterate_files(job.source):                    (sorted relative paths)
            │     excluded? → FILE_EXCLUDED (first matching pattern)
            │     else      → FILE_SELECTED, then executor.handle_file(path, (size, sha256))
            ├─ executor.finalize()
            └─ emit JOB_COMPLETED (+ executor.completed_fields())
```

## Module boundaries

- **`backup_scheduler.py` (CLI layer).** Owns process concerns only: argv, stdout/stderr, exit codes, and turning exceptions into `ERROR:<CODE>:<message>`. It contains the `EventEmitter`, which serializes events as compact JSON (`separators=(",", ":")`) and flushes per line.
- **`scheduler/parser.py` (validation layer).** The only module that sees raw YAML. It turns it into frozen dataclasses or raises `ScheduleValidationError` with a human-readable message. Source paths are resolved and checked here (`mount://` prefix, must stay inside the mount, must be an existing directory).
- **`scheduler/models.py` (domain types).** `Schedule(timezone, timezone_name, jobs)`, `Job(job_id, enabled, source, exclude, when, strategy)`, `JobWhen(kind, time_of_day, days, once_at)`, `JobStrategy(kind, max_pack_bytes)`. Frozen, with no behaviour.
- **`scheduler/executor.py` (behaviour layer).** Pure functions for scheduling (`evaluate_due_jobs`, `_compute_due_locals`), the file walk (`iterate_files`), exclusion matching (`match_exclusion`, `_pattern_matches`), job execution (`run_job`), and the strategy executor classes.

Dependencies point one way: CLI → parser/executor → models/errors. `executor.py` never imports `parser.py`, and neither imports the CLI.

## Strategy executors

`BaseStrategyExecutor` holds `job`, `emit` and `run_time` and defines four hooks:

| Hook | Called | Default |
|---|---|---|
| `kind` (property) | once, for `STRATEGY_SELECTED` | abstract |
| `handle_file(relative_path, (size, checksum))` | per selected file, in order | abstract |
| `finalize()` | once, after the walk | no-op |
| `completed_fields()` | once, merged into `JOB_COMPLETED` | `{}` |

Implementations: `FullStrategyExecutor` (`FILE_BACKED_UP`, tracks `total_size`), `VerifyStrategyExecutor` (`FILE_VERIFIED`), and `PackStrategyExecutor`. The pack executor buffers files into sequential packs bounded by `max_bytes`. A file that would overflow the open pack finalizes that pack first, and a single oversized file still gets its own pack. Each finalized pack is written to a temp dir with deterministic tar metadata and reported as `PACK_CREATED`.

## Invariants

1. `SCHEDULE_PARSED` is the first event, exactly once. Nothing is emitted if validation fails.
2. Jobs run in ascending `job_id`. Files run in lexicographic order of relative POSIX path.
3. All times are floored to the minute. The window `[now, now + duration]` is inclusive at both ends.
4. Disabled jobs are never due and emit nothing.
5. Output bytes are deterministic for the same inputs. That includes checksums: SHA-256 of file bytes, and tar archives with `mtime=0`, `mode=0o644`, `uid=gid=0`, empty user and group names.
