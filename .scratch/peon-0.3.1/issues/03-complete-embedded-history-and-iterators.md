# 03 - Complete embedded history and iterator interfaces

**What to build:** Give embedded callers validated history plus reliable typed
or dictionary callbacks and iterators over one prompt execution.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** ready-for-agent

- [ ] Embedded construction or load accepts typed messages and serialized
  history without terminal imports.
- [ ] Validator covers roles, content, thinking, tool calls/results, usage, and
  field types before provider request or state mutation.
- [ ] Invalid or unknown history returns actionable validation error.
- [ ] Callback, sync iterator, and async iterator support typed or schema-selected
  dictionary events from same serializer.
- [ ] Iterator consumer can retrieve final `TurnResult` without duplicate run.
- [ ] Empty queue polling and terminal completion use distinct signals.
- [ ] Async caller cancellation reaches active turn and worker cleanup is
  deterministic.
- [ ] Buffer size validation and complete-response overflow behavior are
  explicit; no event disappears silently.
- [ ] Embedded imports remain frontend-free with base installation.
- [ ] Focused history/iterator/cancellation tests, full pytest, mypy, and diff
  validation pass.
