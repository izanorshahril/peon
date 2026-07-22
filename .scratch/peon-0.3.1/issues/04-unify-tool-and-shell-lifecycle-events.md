# 04 - Unify tool and shell lifecycle events

**What to build:** Route model-requested tools and direct shell work through same
typed event stream as turns and messages.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** completed

- [x] Tool start precedes execution and includes operation ID, tool name,
  arguments policy, and provider call ID when available.
- [x] Bounded live output events include operation ID, stream name, chunk, and
  deterministic sequence.
- [x] Exactly one tool finish reports success, error, or cancellation plus
  canonical result entering provider history when applicable.
- [x] Model tool calls and direct visible/hidden shell intents share lifecycle
  facts without pretending direct shell is provider tool history.
- [x] Canonical assistant tool-call and tool-result messages persist once.
- [x] Embedded typed/dictionary, schema version 2, journal, and Textual consumers
  receive complete lifecycle.
- [x] Legacy live-output callback is a compatibility adapter over typed events,
  then removed after all in-repo consumers migrate.
- [x] Handler failures do not duplicate tool or shell execution.
- [x] Tool timeout, cancellation, output bounds, process-tree termination, and
  hidden-shell context behavior remain compatible.
- [x] Focused tool/shell/event tests, full pytest, mypy, and diff validation pass.

## Evidence

Validated 2026-07-22:

- All 345 tests passing in full pytest suite (0 failures, 0 errors, 0 xfailed).
- `uv run mypy src/peon`: clean across 28 source files.
- `git diff --check`: clean.
- `ToolStartedEvent`, `ToolOutputEvent`, `ToolFinishedEvent` added to `coding_session.py`, `observability.py`, and `embedded.py`.
- Model-requested tool calls emit `ToolStartedEvent` before execution, `ToolOutputEvent` on output chunks, and `ToolFinishedEvent` on completion/error/cancellation.
- Direct shell commands dispatched via `SessionController.dispatch_shell()` emit identical tool lifecycle events with `source="shell"` without injecting extraneous message history.
- Schema version 1 and 2 serializers support all new tool lifecycle events.
