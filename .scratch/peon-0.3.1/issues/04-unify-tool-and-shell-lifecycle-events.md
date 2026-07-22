# 04 - Unify tool and shell lifecycle events

**What to build:** Route model-requested tools and direct shell work through same
typed event stream as turns and messages.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** ready-for-agent

- [ ] Tool start precedes execution and includes operation ID, tool name,
  arguments policy, and provider call ID when available.
- [ ] Bounded live output events include operation ID, stream name, chunk, and
  deterministic sequence.
- [ ] Exactly one tool finish reports success, error, or cancellation plus
  canonical result entering provider history when applicable.
- [ ] Model tool calls and direct visible/hidden shell intents share lifecycle
  facts without pretending direct shell is provider tool history.
- [ ] Canonical assistant tool-call and tool-result messages persist once.
- [ ] Embedded typed/dictionary, schema version 2, journal, and Textual consumers
  receive complete lifecycle.
- [ ] Legacy live-output callback is a compatibility adapter over typed events,
  then removed after all in-repo consumers migrate.
- [ ] Handler failures do not duplicate tool or shell execution.
- [ ] Tool timeout, cancellation, output bounds, process-tree termination, and
  hidden-shell context behavior remain compatible.
- [ ] Focused tool/shell/event tests, full pytest, mypy, and diff validation pass.
