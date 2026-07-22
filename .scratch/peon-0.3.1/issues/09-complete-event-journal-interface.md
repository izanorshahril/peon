# 09 - Complete event journal interface

**What to build:** Finish explicit schema version 2 event journaling for audit
or replay without changing sessions, traces, or logging.

**Blocked by:** 02 - Complete runtime events and shared serializers; 04 - Unify
tool and shell lifecycle events; 08 - Complete streaming cancellation and
backpressure.

**Status:** ready-for-agent

- [ ] Journal remains disabled by default and requires explicit output and
  strictness/redaction policy.
- [ ] CLI and embedded/application composition expose journal sink without core
  depending on filesystem path.
- [ ] Shared schema version 2 serializer covers lifecycle, deltas, tools,
  commands/selections, cancellation, and terminal results.
- [ ] Redaction hook transforms or removes content without mutating in-process
  event.
- [ ] README and CLI help warn prompts, assistant content, tool arguments/output,
  paths, and secrets may be written.
- [ ] Append and trailing-partial-record recovery behavior is documented and
  tested.
- [ ] Non-strict failure emits diagnostic and preserves turn/session state.
- [ ] Strict failure produces declared terminal journal/consumer error exactly
  once without corrupting canonical messages.
- [ ] Session files contain canonical messages only; traces remain metadata-only;
  logging remains diagnostic.
- [ ] Focused journal/redaction/recovery tests, full pytest, mypy, build, and diff
  validation pass.
