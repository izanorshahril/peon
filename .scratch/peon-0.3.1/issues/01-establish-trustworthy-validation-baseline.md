# 01 - Establish trustworthy 0.3.1 validation baseline

**What to build:** Make repository validation deterministic before changing
runtime behavior. Characterize current public behavior and known failures so
later tickets cannot claim completion from partial test runs.

**Blocked by:** None.

**Status:** completed

- [x] `uv run pytest` collects only maintained Peon tests, not vendored
  `reference/` suites, and reports exact pass/fail summary.
- [x] `uv run pytest --collect-only -q` records maintained test count.
- [x] `uv run mypy src/peon`, `uv build`, and `git diff --check` pass.
- [x] Characterization tests reproduce async iterator premature completion,
  missing tool events, schema version 1 output, and current 0.2 session loading.
- [x] Characterization tests use public behavior, not private helper calls.
- [x] Current package/version, optional extras, and import graph are recorded.
- [x] No runtime behavior changes enter this ticket except validation discovery
  configuration required to isolate maintained tests.
- [x] `project-history.md` records dated baseline evidence after checks pass.

## Evidence

Validated 2026-07-22:

- Root collection: 312 maintained tests; vendored `reference/` tests excluded by
  pytest `testpaths`.
- Root full suite: 312 tests, 0 failures, 0 errors, 2 strict expected failures,
  25.366 seconds, exit 0.
- Embedded focus: 6 passed, 2 xfailed.
- Schema-v1 CLI and legacy-session focus: 62 passed.
- Mypy: success across 28 source files.
- Build: `peon-0.3.0a0` sdist and wheel created successfully.
- Diff check: no whitespace errors.
- Embedded import graph: `peon.agent`, application controller/session/resources,
  `peon.embedded`, and extension registry/filesystem/sample modules; no Textual
  or prompt-toolkit module loaded.
