# 01 — Freeze 0.2.0 baseline and contracts

**What to build:** Preserve the known-working Peon 0.2.0 build before migration. Validate the current commit, create a safety tag and detached backup worktree, create an isolated 0.3.0 feature worktree, and add external-behavior characterization tests that later tickets can use as compatibility gates.

**Blocked by:** None — can start immediately.

**Status:** completed

- [x] The tracked baseline is clean and passes full pytest, static typing, and diff validation before any migration branch is created.
- [x] An annotated safety tag identifies the validated 0.2.0 commit.
- [x] A detached backup worktree at that commit independently passes full pytest and static typing and is treated as read-only.
- [x] A separate 0.3.0 feature worktree and branch start from the same validated commit; `main` remains untouched.
- [x] Ignored local spec, review, and ticket documents are available in the feature worktree without being force-added.
- [x] Characterization tests lock current coding-session event order, schema version 1 JSON events, canonical session persistence, embedded frontend-free imports, Textual prompt/command/session/resource/shell behavior, and cancellation.
- [x] Tests assert only public observable behavior, not private implementation details.
- [x] Full pytest, static typing, and diff validation pass after the tests-only checkpoint.
