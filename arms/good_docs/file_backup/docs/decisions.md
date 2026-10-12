# Design decisions

Short records of why things are the way they are. Change them deliberately, not incidentally.

### D1. Validate everything before emitting anything
The whole schedule is parsed and validated in `load_schedule` before the first event. An invalid schedule therefore produces exactly one error line and no partial event stream, which the error contract requires. Executor code can then assume valid input.

### D2. Events go through an `emit` callback
`run_job` and the strategy executors receive `emit: Callable[[dict], None]` rather than a stream. Library code stays independent of stdout and JSON formatting, and it is easy to capture events in memory. The CLI's `EventEmitter` is the only serializer.

### D3. Frozen dataclasses as the domain model
Models are immutable values produced by the parser. Nothing mutates a `Job` mid-run, so jobs can be shared across due times without surprises.

### D4. Strategies as small classes with hooks
`full`, `verify` and `pack` differ only in what happens per selected file and at the end of a job. Hooks (`handle_file`, `finalize`, `completed_fields`) let `run_job` own the walk, exclusion and counting once. Strategies own only what differs.

### D5. Own glob matcher
The exclusion semantics (case-sensitive, `**` crossing `/`, patterns relative to `source`, first match wins) don't match `pathlib`/`glob` exactly. `_pattern_matches` implements them directly, matching segment by segment with `fnmatchcase`, and memoizes pattern splitting.

### D6. Deterministic archives
Packs use GNU tar format with fixed metadata, so checksums are reproducible across machines and runs. Any new archive or checksum output must follow the same rule.
