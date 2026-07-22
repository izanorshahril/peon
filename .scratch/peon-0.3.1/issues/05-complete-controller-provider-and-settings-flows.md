# 05 - Complete controller provider and settings flows

**What to build:** Put model selection, provider setup, settings, and logout
effects fully behind host-neutral controller interfaces.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** completed

- [x] Controller imports app-owned config/provider modules, never CLI rendering
  helpers or Textual classes.
- [x] `/model`, `/provider`, `/settings`, and `/logout` complete through typed
  intents, outcomes, and continuation responses.
- [x] Provider discovery, validation, persistence, active-model switching,
  logout replacement, and reasoning capability behavior remain compatible.
- [x] Selection/input requests use stable semantic option IDs and safe metadata.
- [x] Continuation tokens are scoped and single-use; invalid, stale, replayed,
  or cross-session values fail without mutation.
- [x] Secrets never enter runtime events, logs, traces, sessions, journals, or
  error text.
- [x] Failed provider/config operations leave active and persisted state intact.
- [x] Headless tests drive every full workflow without terminal input or widgets.
- [x] Existing prompt, informational-command, and session-transition controller
  behavior remains green.
- [x] Focused controller/config/provider tests, full pytest, mypy, and diff
  validation pass.

## Evidence

Validated 2026-07-22:

- All 352 tests passing in full pytest suite (0 failures, 0 errors).
- `uv run mypy src/peon`: clean across 28 source files.
- `git diff --check`: clean.
- `ProviderConfig`, `SavedModel`, `saved_model_choices`, `select_saved_model`, and setting specs moved from `cli.py` to `config.py`.
- `SessionController` imports 0 symbols from `peon.app.cli`.
- Multi-step `/provider` setup, `/model` selection, `/settings` inspection/update, and `/logout` flows fully supported via typed controller intents, outcomes, and single-use continuation tokens.
- Secret fields (API keys, Copilot tokens) flagged with `is_secret=True` and masked in errors/logs.
- Added headless suite `tests/test_controller_provider_settings.py` verifying all workflows without terminal or Textual dependencies.
