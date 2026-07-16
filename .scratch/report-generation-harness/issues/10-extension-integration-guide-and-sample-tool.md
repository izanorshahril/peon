# 10 — Extension integration guide and sample tool

**What to build:** A small example extension and developer-facing integration path that proves an external application can add a domain tool without changing Peon's core. The existing report-building application's Excel component is the documented future integration target, not a dependency of this ticket.

**Blocked by:** 08 — Tool registry and extension contract; 09 — Tool-call continuation and compact context

**Status:** ready-for-agent

- [ ] A sample extension registers at least one useful tool through the public extension contract.
- [ ] The README explains how a separate application can wrap an existing capability as a Peon tool, skill, or extension.
- [ ] The report-building application's Excel reader/writer is named as an external integration candidate and is not imported by the core.
- [ ] The sample extension can be tested through the same task -> tool -> continuation path as any future domain integration.
- [ ] No report-specific schema, workbook dependency, or image-processing dependency is added to Peon's core for this ticket.
