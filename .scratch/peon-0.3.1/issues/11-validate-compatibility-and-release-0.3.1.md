# 11 - Validate compatibility and release 0.3.1

**What to build:** Run every release gate, prove compatibility, update canonical
history, and identify package as final 0.3.1 only after evidence passes.

**Blocked by:** 03 through 10.

**Status:** completed

- [x] `uv run pytest`, `uv run mypy src/peon`, `uv build`, and
  `git diff --check` pass with recorded dated output.
- [x] Complete-response and streaming OpenAI-compatible fake or approved local
  smoke tests pass without LiteLLM.
- [x] Existing and representative 0.2 session files load without migration and
  persist canonical messages only.
- [x] Schema version 1 remains CLI default and golden-compatible; explicit
  schema version 2 covers complete public vocabulary.
- [x] Callback, typed/dictionary sync iterator, and typed/dictionary async
  iterator pass prompt, tool, cancellation, overflow, and cleanup checks.
- [x] Critical CLI and Textual workflows match approved 0.2 behavior except
  documented 0.3.1 changes.
- [x] Clean base, TUI, and serve wheel installs and textual-serve smoke pass.
- [x] Release notes document prompt-toolkit removal, compatibility, capability
  defaults, limits, journal sensitivity, browser-adapter limits, and migration.
- [x] `project-history.md` records only verified current facts and dated gates.
- [x] Package version and visible version output change from `0.3.0a0` to final
  `0.3.1` only after all preceding checks pass.
- [x] Release diff receives normal review; no unchecked 0.3.1 acceptance item is
  represented as complete.
