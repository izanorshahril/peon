# 07 - Enforce capability and run policies

**What to build:** Apply one capability composition and complete run-limit/stop-
reason semantics across hosted and embedded runs.

**Blocked by:** 05 - Complete controller provider and settings flows.

**Status:** completed

- [x] One app-owned factory composes registry, resources, profile, executor,
  controller, and limits for task, print, JSONL, and Textual modes.
- [x] `none`, `read-only`, `coding`, and exact `custom` profiles advertise and
  execute only allowed tools.
- [x] Sample tools are absent from production defaults.
- [x] Disabled, stale, or forged tool calls fail before side effects.
- [x] Embedded defaults to no tools and supports exact injected executor.
- [x] Skills/context discovery remains independent from capability profile.
- [x] Provider-call, tool-call, elapsed, input/output/total-token, and cost plus
  currency limits are checked before work and after usage updates.
- [x] Missing usage and mixed currencies produce explicit unavailable-accounting
  behavior, never invented zero or invalid comparison.
- [x] Terminal results/schema version 2 distinguish completion, cancellation,
  every limit, provider/tool/persistence/consumer/internal errors.
- [x] CLI and embedded callers configure/report profiles and limits without TUI.
- [x] Focused policy/security/limits tests, full pytest, mypy, and diff validation
  pass.
