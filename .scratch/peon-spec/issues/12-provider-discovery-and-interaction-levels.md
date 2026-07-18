# 12 - Provider discovery and interaction levels

**What to build:** Make local OpenAI-compatible endpoints usable without
authentication, discover their available models, and expose an explicit
interaction-level boundary for the CLI.

**Blocked by:** 07 - Normalized provider adapter; 11 - Interactive TUI and
provider configuration

**Status:** complete

- [x] OpenAI-compatible API keys are optional.
- [x] Authorization is omitted when no API key is configured.
- [x] OpenAI-compatible providers discover model IDs through `GET /models`.
- [x] Minimal interactive mode displays discovered models and accepts a number
  or exact model ID.
- [x] Level 1 `non-interactive` and level 2 `minimal` are available.
- [x] A task defaults to level 1; no task defaults to level 2.
- [x] Level 3 `fullscreen` and level 4 `webapp` are reserved with clear
  unavailable-mode errors.
- [x] The current boundary is documented: the minimal shell is a
  standard-library REPL with in-memory context, without a read tool or
  persistent history.