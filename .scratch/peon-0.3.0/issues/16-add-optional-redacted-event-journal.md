# 16 — Add optional redacted event journal

**What to build:** Let automation operators opt into a complete schema version 2 runtime-event journal for audit or replay. Journaling is separate from canonical session state and metadata traces, warns about sensitive content, supports redaction, and has explicit strict or isolated failure behavior.

**Blocked by:** 14 — Stream OpenAI-compatible responses end to end; 15 — Bound streaming iterator delivery.

**Status:** completed

- [x] Journaling is disabled by default and requires an explicit output plus policy.
- [x] The journal uses the shared schema version 2 serializer for lifecycle, delta, tool, command, and terminal events.
- [x] Documentation and CLI help state that prompts, assistant content, tool arguments/output, paths, and secrets may appear.
- [x] A redaction hook can transform or remove sensitive fields before encoding without mutating in-process events.
- [x] Appends are safe against partial trailing records according to declared recovery behavior.
- [x] Non-strict journal failure emits a diagnostic and leaves turn/session state intact; strict mode produces the declared terminal failure.
- [x] Normal conversation sessions still persist canonical messages only.
- [x] Metadata traces remain content-free and standard logging remains diagnostic rather than an event journal.
- [x] Core/controller depend on a journal sink interface, not a JSONL path.
- [x] Focused journal/redaction/failure/persistence/trace, full pytest, static typing, and diff validation pass.
