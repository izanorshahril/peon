# 13 — Retire prompt-toolkit host

**What to build:** Make Textual the sole maintained interactive TUI after controller and Textual parity is proved. Remove prompt-toolkit runtime code, dependency, and duplicate tests while old explicit host selection fails with actionable guidance.

**Blocked by:** 12 — Complete thin Textual migration.

**Status:** completed

- [x] Controller and Textual tests prove retained prompt, command, provider, settings, session, resource, tool, shell, and cancellation behavior before removal.
- [x] Prompt-toolkit implementation and host-specific orchestration are removed.
- [x] Prompt-toolkit is removed from runtime dependencies and no source import references it.
- [x] Host discovery no longer reports prompt-toolkit as available.
- [x] Explicit old host selection returns an actionable unavailable-host error without traceback.
- [x] Print, JSONL, embedded, and future adapter roles remain available and are not treated as competing TUIs.
- [x] Textual remains the default interactive startup and retains characterized behavior.
- [x] Obsolete duplicate tests are removed only after equivalent controller or Textual coverage exists.
- [x] Import and package metadata checks prove prompt-toolkit is absent.
- [x] Focused host/CLI/Textual, full pytest, static typing, and diff validation pass.
