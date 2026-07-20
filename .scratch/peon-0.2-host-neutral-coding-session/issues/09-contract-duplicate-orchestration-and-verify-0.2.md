# 09 — Contract duplicate orchestration and verify Peon 0.2

**What to build:** Finish the expand-contract migration by removing superseded host orchestration, publishing the new module ownership as current project truth, and verifying that Peon 0.2 retains existing behavior across every migrated host.

**Blocked by:** 02 — Serialize JSON mode from session events; 03 — Expose normalized provider usage end to end; 04 — Add metadata-only performance traces; 05 — Expose the embedded Python adapter; 06 — Route Textual turns through CodingSession; 07 — Route the prompt-toolkit fallback through CodingSession; 08 — Centralize host selection and unavailable-host errors.

**Status:** completed

**Completed in:** working tree after Ticket 08

**Validation:** Full pytest and static type check passed after the final
orchestration, version, and documentation changes.

- [x] Duplicate prompt preparation, tool execution, message persistence, cancellation, and event orchestration are removed from migrated hosts rather than retained beside `CodingSession`.
- [x] Deleting `CodingSession` would force shared behavior back into multiple hosts, demonstrating that the module is deep rather than a pass-through.
- [x] Package dependency direction remains intact: the agent layer imports no application or concrete integrations, and provider quirks remain in provider adapters.
- [x] The current linear session format and existing conversation files require no migration for Peon 0.2.
- [x] Current-state documentation records the implemented session, factory, host, embedded, usage, and observability responsibilities without treating architecture review text as current truth.
- [x] Development and release version metadata follow the approved 0.2 pre-release and release policy, with the stable 0.1 baseline retained in Git history rather than a copied source tree.
- [x] Print, JSON event, Textual, prompt-toolkit, embedded, provider, session, resource, extension, and tool behavior all pass the complete regression suite.
- [x] The full test suite and static type check pass from a clean checkout, with any remaining fullscreen, RPC/web, multimodal, compaction, and extension-discovery work still reported as follow-up scope.