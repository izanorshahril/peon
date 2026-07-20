# 07 — Route the prompt-toolkit fallback through CodingSession

**What to build:** Make the prompt-toolkit fallback consume the shared `CodingSession` interface while preserving its intentionally smaller interaction and session contract. The fallback no longer owns duplicate prompt execution, resource application, persistence, or cancellation logic.

**Blocked by:** 01 — Route print mode through CodingSession.

**Status:** completed

**Completed in:** working tree after Ticket 06

**Validation:** Focused fallback and session tests passed, followed by the
full test suite and static type check.

- [x] Prompt submission delegates to `CodingSession` and produces the same final result, failures, resources, tools, and persistence semantics as other hosts.
- [x] New, named, resumed, forked, durable, and ephemeral sessions retain the currently supported fallback behavior.
- [x] Resource prompts are reapplied exactly once where required and are excluded from persisted conversation history.
- [x] Supported cancellation and exit behavior translates to the session interface without depending on Textual classes.
- [x] The fallback remains deliberately smaller and does not gain Textual-only widgets, pickers, or rendering requirements.
- [x] Superseded execution and persistence code is removed after compatibility tests prove the migrated path.
- [x] Focused fallback session and resource tests pass, followed by the full test suite and static type check.