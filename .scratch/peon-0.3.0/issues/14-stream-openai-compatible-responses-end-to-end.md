# 14 — Stream OpenAI-compatible responses end to end

**What to build:** Stream verified OpenAI-compatible provider responses through the provider-neutral runtime into schema version 2 and Textual. Users see text, thinking, and assembled tool calls incrementally while final canonical history, complete-response fallback, cancellation, timeout, and retry safety remain correct.

**Blocked by:** 11 — Enforce run limits and stop reasons; 12 — Complete thin Textual migration.

**Status:** ready-for-agent

- [ ] Providers retain required complete-response behavior and may opt into a separate streaming interface by capability rather than provider-name branching.
- [ ] OpenAI-compatible SSE parsing handles text, thinking, fragmented tool arguments, usage updates, finish reasons, malformed frames, and disconnects with fake transports.
- [ ] Provider-specific fragments are normalized in the AI adapter before reaching the agent loop.
- [ ] Text/thinking deltas carry stable message identity and sequence; one final canonical message reconciles without duplicate text.
- [ ] Streaming tool calls assemble into valid canonical calls before execution and emit the established tool lifecycle.
- [ ] Cancellation closes active response transport where supported and configurable request timeout bounds blocking transport work.
- [ ] Retries occur only before visible output or side effects, preventing duplicated text or tool execution.
- [ ] Non-streaming and streaming paths produce equivalent final conversation history and usage for equivalent provider responses.
- [ ] Textual renders live text/thinking/tool progress; schema version 2 emits deltas; schema version 1 and complete-response providers remain compatible.
- [ ] Unverified custom endpoint contracts do not advertise streaming.
- [ ] Focused provider/stream/controller/Textual/JSONL, full pytest, static typing, and diff validation pass.
