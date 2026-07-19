# 03 — Pi-Compatible Print and Event Modes

**What to build:** Peon supports one-shot prompt execution for scripts, including piped standard input and machine-readable JSON-line events, without accidentally continuing an unrelated durable session.

**Blocked by:** 01 — Explicit Session Lifecycle and Legacy Compatibility.

**Status:** complete

- [x] `-p` and `--print` accept a prompt, execute one agent interaction, and exit.
- [x] Print text mode writes only the final assistant response without interactive headers, status notices, or transcript decoration.
- [x] Piped standard input is incorporated into the initial prompt on supported Windows shells.
- [x] Print mode creates an ephemeral session by default and never resumes the newest durable session implicitly.
- [x] Explicit session options can opt print mode into the documented durable or continuing session behavior.
- [x] JSON-line output emits parseable normalized lifecycle, assistant, thinking, tool-call, tool-result, and error events in order.
- [x] Provider and tool failures produce a useful non-zero result without corrupting machine-readable output.
- [x] CLI tests cover text output, piped input, ephemeral persistence, explicit session behavior, event ordering, and failure handling.
