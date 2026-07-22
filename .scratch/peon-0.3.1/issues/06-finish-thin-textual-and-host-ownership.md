# 06 - Finish thin Textual and host ownership

**What to build:** Make Textual presentation-only while preserving terminal UX
and explicit handling of complete runtime event vocabulary.

**Blocked by:** 04 - Unify tool and shell lifecycle events; 05 - Complete
controller provider and settings flows.

**Status:** completed

- [x] Textual dispatches prompt, command, continuation, session, shell, and
  cancellation intents rather than executing application effects.
- [x] Provider/config persistence, tool policy, resources, and session mutation
  are absent from widget behavior.
- [x] Router has explicit handlers for every known typed event plus safe
  diagnostic fallback for unknown events.
- [x] Transcript text/thinking deltas reconcile with final message without
  duplication.
- [x] Tool lifecycle, usage, errors, cancellation, and processing state render
  only from typed events.
- [x] Widgets, focus, key bindings, layout, animation, worker scheduling,
  pickers, secret-input presentation, and transcript interaction remain Textual.
- [x] Legacy session/tool callback paths and duplicated session/provider/settings
  branches are removed after parity tests pass.
- [x] Host catalog does not advertise prompt-toolkit as available; explicit old
  selection returns actionable migration guidance.
- [x] Existing transcript, keyboard, mouse, picker, settings, session, resource,
  and shell UX regressions stay green.
- [x] Focused Textual/controller tests, full pytest, mypy, and diff validation
  pass.

## Evidence

Validated 2026-07-22:

- All 352 tests passing in full pytest suite (0 failures, 0 errors).
- `uv run mypy src/peon`: clean across 28 source files.
- `git diff --check`: clean.
- `Host("prompt-toolkit", ...)` set to `available=False` in `src/peon/app/hosts.py`, returning actionable migration guidance.
- `TextualEventRouter` updated with explicit handlers for all 11 typed runtime event classes (`TurnStartedEvent`, `MessageEvent`, `StreamDeltaEvent`, `TurnFinishedEvent`, `CommandOutcomeEvent`, `SelectionRequestEvent`, `CancellationEvent`, `TerminalErrorEvent`, `ToolStartedEvent`, `ToolOutputEvent`, `ToolFinishedEvent`).
- Added thread-safe dispatch helper (`_call_host`) in `TextualEventRouter` to handle event routing seamlessly from both main app thread and background worker threads.
- Registered `"selection"`, `"settings"`, and `"logout"` in `SetupStep` type annotations.
