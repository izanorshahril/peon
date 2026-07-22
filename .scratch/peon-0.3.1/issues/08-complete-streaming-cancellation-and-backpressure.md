# 08 - Complete streaming cancellation and backpressure

**What to build:** Make streaming equivalent to complete responses while
handling timeout, transport cancellation, retry, and slow consumers safely.

**Blocked by:** 03 - Complete embedded history and iterator interfaces; 04 -
Unify tool and shell lifecycle events; 07 - Enforce capability and run policies.

**Status:** ready-for-agent

- [ ] OpenAI-compatible SSE parser covers text, thinking, fragmented tool
  arguments, usage, finish reasons, malformed frames, and disconnects.
- [ ] Provider-specific fragments are fully normalized inside AI adapter.
- [ ] Request timeout is configurable and bounds connection/read work.
- [ ] Cancellation closes active response transport where supported and prevents
  later tool/provider continuation.
- [ ] Retry occurs only before visible output or side effects.
- [ ] Deltas carry stable message identity and assigned event sequence; final
  canonical message reconciles without duplicate content.
- [ ] Streaming tool calls assemble valid canonical calls before execution and
  use unified lifecycle events.
- [ ] Finite iterator buffer coalesces only adjacent compatible delta/output
  events while preserving cross-family order and final content.
- [ ] Canonical messages, tool finish, failures, cancellation, and turn finish
  never drop; unrecoverable overflow yields consumer-error stop reason.
- [ ] Iterator closure leaves no worker/thread or active transport running.
- [ ] Equivalent streaming and complete fake responses yield equivalent history
  and usage; focused/full tests, mypy, and diff validation pass.
