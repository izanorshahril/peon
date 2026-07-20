# 08 — Centralize host selection and unavailable-host errors

**What to build:** Give built-in frontends one small host interface and select them by stable identifiers during startup composition. Implemented hosts start normally, while reserved, missing, or unsupported hosts fail with clear feedback before coding-session work begins.

**Blocked by:** 06 — Route Textual turns through CodingSession; 07 — Route the prompt-toolkit fallback through CodingSession.

**Status:** completed

**Completed in:** working tree after Ticket 07

**Validation:** Focused host, startup, CLI, and fallback tests passed,
followed by the full test suite and static type check.

- [x] Print, JSON event, Textual, prompt-toolkit, and embedded entry paths have explicit host roles without moving presentation behavior into `CodingSession`.
- [x] Stable built-in identifiers resolve to the correct host, and existing command-line mode selection remains compatible.
- [x] Reserved or missing fullscreen and web hosts return actionable unavailable-host errors without creating or mutating a conversation.
- [x] A complete host is distinct from a tool extension, lifecycle hook, UI contribution, and declarative theme.
- [x] Host-specific UI capabilities remain optional and cannot become required dependencies of the coding-session interface.
- [x] Third-party package discovery is not introduced until independently packaged host adapters create a concrete need.
- [x] Focused startup, selection, unavailable-host, and import-isolation tests pass, followed by the full test suite and static type check.