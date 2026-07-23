# 08 - Complete streaming cancellation and backpressure

**What to build:** Make streaming equivalent to complete responses while
handling timeout, transport cancellation, retry, and slow consumers safely.

**Blocked by:** 03 - Complete embedded history and iterator interfaces; 04 -
Unify tool and shell lifecycle events; 07 - Enforce capability and run policies.

**Status:** completed

- [x] OpenAI-compatible SSE parser covers text, thinking, fragmented tool
  arguments, usage, finish reasons, malformed frames, and disconnects.
- [x] Provider-specific fragments are fully normalized inside AI adapter.
- [x] Request timeout is configurable and bounds connection/read work.
- [x] Cancellation closes active response transport where supported and prevents
  later tool/provider continuation.
- [x] Retry occurs only before visible output or side effects.
- [x] Deltas carry stable message identity and assigned event sequence; final
  canonical message reconciles without duplicate content.
- [x] Streaming tool calls assemble valid canonical calls before execution and
  use unified lifecycle events.
- [x] Finite iterator buffer coalesces only adjacent compatible delta/output
  events while preserving cross-family order and final content.
- [x] Canonical messages, tool finish, failures, cancellation, and turn finish
  never drop; unrecoverable overflow yields consumer-error stop reason.
- [x] Iterator closure leaves no worker/thread or active transport running.
- [x] Equivalent streaming and complete fake responses yield equivalent history
  and usage; focused/full tests, mypy, and diff validation pass.
