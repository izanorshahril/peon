# 09 — Tool-call continuation and compact context

**What to build:** The multi-turn agent path where a model can request a registered tool, Peon executes it, appends the result to compact context, and asks the provider for the next turn.

**Blocked by:** 06 — Minimal agent loop and command boundary; 07 — Normalized provider adapter; 08 — Tool registry and extension contract

**Status:** ready-for-agent

- [ ] A tool call from the provider resolves against the extension registry and invokes the matching handler.
- [ ] The tool result is appended to context and included in the continuation turn.
- [ ] The loop returns a final response when the provider stops requesting tools.
- [ ] Unknown tools, invalid inputs, provider failures, and exhausted tool-call limits produce clear errors.
- [ ] A public-seam test verifies one complete task -> tool -> continuation -> final response flow.
