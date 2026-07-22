# 07 - Enforce capability and run policies

**What to build:** Apply one capability composition and complete run-limit/stop-
reason semantics across hosted and embedded runs.

**Blocked by:** 05 - Complete controller provider and settings flows.

**Status:** ready-for-agent

- [ ] One app-owned factory composes registry, resources, profile, executor,
  controller, and limits for task, print, JSONL, and Textual modes.
- [ ] `none`, `read-only`, `coding`, and exact `custom` profiles advertise and
  execute only allowed tools.
- [ ] Sample tools are absent from production defaults.
- [ ] Disabled, stale, or forged tool calls fail before side effects.
- [ ] Embedded defaults to no tools and supports exact injected executor.
- [ ] Skills/context discovery remains independent from capability profile.
- [ ] Provider-call, tool-call, elapsed, input/output/total-token, and cost plus
  currency limits are checked before work and after usage updates.
- [ ] Missing usage and mixed currencies produce explicit unavailable-accounting
  behavior, never invented zero or invalid comparison.
- [ ] Terminal results/schema version 2 distinguish completion, cancellation,
  every limit, provider/tool/persistence/consumer/internal errors.
- [ ] CLI and embedded callers configure/report profiles and limits without TUI.
- [ ] Focused policy/security/limits tests, full pytest, mypy, and diff validation
  pass.
