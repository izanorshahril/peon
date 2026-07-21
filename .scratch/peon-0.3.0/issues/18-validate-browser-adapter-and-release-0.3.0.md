# 18 — Validate browser adapter and release 0.3.0

**What to build:** Prove the migrated Textual application can run through textual-serve as a local adapter, complete every 0.3.0 release gate, preserve 0.2 sessions and JSON schema version 1, publish schema version 2 behavior, and only then identify the build as Peon 0.3.0.

**Blocked by:** 14 — Stream OpenAI-compatible responses end to end; 15 — Bound streaming iterator delivery; 16 — Add optional redacted event journal; 17 — Split headless, TUI, and serve packaging.

**Status:** ready-for-agent

- [ ] A local textual-serve smoke test reaches initial render and verifies prompt submission, streamed output, tool display, and cancellation.
- [ ] Release notes state that textual-serve is an adapter, not native browser UI or production authentication, tenancy, scaling, or public deployment.
- [ ] Complete-response and streaming OpenAI-compatible paths pass approved fake or local smoke tests without LiteLLM.
- [ ] Existing and legacy session files load without migration and persist canonical messages only.
- [ ] JSON event schema version 1 remains the compatibility default; schema version 2 covers the complete runtime vocabulary.
- [ ] Clean base, TUI, and serve wheel installations pass import/startup smoke tests.
- [ ] Critical CLI and Textual workflows match the validated 0.2 backup except for explicitly approved 0.3.0 changes.
- [ ] Full pytest, static typing, build, diff validation, and package metadata checks pass.
- [ ] Version metadata and visible banners change to 0.3.0 only after all preceding criteria pass.
- [ ] Canonical project history records completed architecture facts, prompt-toolkit removal, compatibility decisions, and dated validation evidence.
- [ ] Release commit is ready for normal review; the 0.2 safety tag and backup worktree remain until post-release verification completes.
