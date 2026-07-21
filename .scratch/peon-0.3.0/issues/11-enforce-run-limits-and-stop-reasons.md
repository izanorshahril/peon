# 11 — Enforce run limits and stop reasons

**What to build:** Let automation callers bound provider calls, tool calls, elapsed time, tokens, and optional cost. Every terminal result and schema version 2 event identifies a precise machine-readable stop reason while existing status categories and opt-in defaults remain compatible.

**Blocked by:** 05 — Dispatch prompts through SessionController.

**Status:** ready-for-agent

- [ ] Immutable run policy supports optional provider-call, tool-call, elapsed-time, input-token, output-token, total-token, and cost/currency limits.
- [ ] Omitted limits preserve existing direct caller behavior.
- [ ] Limits are checked before provider/tool work and after usage updates with injected clocks for deterministic tests.
- [ ] Provider and tool continuation cannot exceed configured call limits.
- [ ] Missing token/cost usage follows explicit unavailable-accounting policy and is never treated as zero.
- [ ] Mixed currencies are not summed or compared as one cost.
- [ ] Terminal results distinguish completed, cancelled, each limit, provider error, tool error, persistence error, consumer error, and internal error.
- [ ] Existing success/error/cancelled status remains compatible while stop reason adds precision.
- [ ] Schema version 2 serializes limits and stop reasons; schema version 1 remains compatible.
- [ ] CLI and embedded callers can configure limits without importing a TUI.
- [ ] Focused limits/usage/controller/JSONL, full pytest, static typing, and diff validation pass.
