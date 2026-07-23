# 09 - Complete event journal interface

**What to build:** Finish explicit schema version 2 event journaling for audit
or replay without changing sessions, traces, or logging.

**Blocked by:** 02 - Complete runtime events and shared serializers; 04 - Unify
tool and shell lifecycle events; 08 - Complete streaming cancellation and
backpressure.

**Status:** completed

- [x] Journal remains disabled by default and requires explicit output and
  strictness/redaction policy.
- [x] CLI and embedded/application composition expose journal sink without core
  depending on filesystem path.
- [x] Shared schema version 2 serializer covers lifecycle, deltas, tools,
  commands/selections, cancellation, and terminal results.
- [x] Redaction hook transforms or removes content without mutating in-process
  event.
- [x] README and CLI help warn prompts, assistant content, tool arguments/output,
  paths, and secrets may be written.
- [x] Append and trailing-partial-record recovery behavior is documented and
  tested.
- [x] Non-strict failure emits diagnostic and preserves turn/session state.
- [x] Strict failure produces declared terminal journal/consumer error exactly
  once without corrupting canonical messages.
- [x] Session files contain canonical messages only; traces remain metadata-only;
  logging remains diagnostic.
- [x] Focused journal/redaction/recovery tests, full pytest, mypy, build, and diff
  validation pass.
