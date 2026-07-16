## Destination

Peon is a minimal, modular Python agent core. It should reproduce the useful center of Tau and Minion: a small task-to-model loop with compact context and clear provider boundaries. It should borrow Pi's extension shape so tools, skills, and domain integrations can be added without growing the core into an application framework.

Excel report generation is not a Peon workflow. The existing report-building application owns workbook read/write behavior; its components may later be exposed to Peon as tools, skills, or an extension.

## Target package layout

```text
src/peon/
├── ai/          provider and model adapters
├── agent/       portable runtime, messages, tools, events, and harness
├── app/         shell, CLI, TUI, configuration, and presentation policy
└── extensions/  extension API, registry, discovery, and loading
```

Dependency direction:

```text
app -> extensions -> agent
app -> ai --------> agent
```

Use `agent` instead of `core`: it names the reusable behavior and matches Tau's `tau_agent` and Pi's `agent` packages. Keep `core` as a design term for the portable center, not as a vague package name. Keep `tui` inside `app` until the UI becomes large enough to deserve its own package.

## Notes

- Keep the first cut small and modular; prefer a narrow loop and explicit extension points over a framework-heavy core.
- Optimize for a usable agent loop first, not report generation, coding automation, or UI polish.
- Follow workspace constraints: user-space, portable, self-contained, offline-friendly tooling; pick stack on deployment constraints before speed.
- Inspiration refs: Tau and Minion for the minimal loop and compact context handling; Pi for modular providers, tools, and extensions; Hermes Agent remains a later reference for self-improvement ideas.
- Keep the first implementation surface swappable so later tools, skills, runners, or UIs can slot in without rewriting the core loop.

## Decisions so far

- [Minimal core boundary](.scratch/report-generation-harness/issues/01-minimal-core-boundary.md) — The core is a small task/context/provider/tool loop. It does not own report generation or any domain-specific reader/writer.
- [Extension boundary](.scratch/report-generation-harness/issues/02-workbook-evidence-contract.md) — Excel read/write belongs to the existing report-building application and can later be wrapped as a Peon tool, skill, or extension. No workbook contract belongs in the core.
- [Provider surface](.scratch/report-generation-harness/issues/03-provider-surface.md) — Use one normalized model/provider shape by default; keep OpenAI-compatible and GitHub Copilot compatibility inside provider adapters and split the surface only when necessary.
- [Tech stack choice](.scratch/report-generation-harness/issues/04-tech-stack-choice.md) — Python first; Go only if single-binary deployment becomes the dominant constraint.
- [Loop and extension pipeline](.scratch/report-generation-harness/issues/05-shared-justification-pipeline.md) — The shared loop ends at model response, tool-call dispatch, and compact context updates. Extension-specific behavior stays inside extensions.

## Deferred by design

- Extension discovery and packaging details beyond a small in-process registry.
- Context compaction and persistence policies beyond the minimum needed for a working loop.
- TUI, web, dashboard, autonomous coding, self-improvement, and multi-agent behavior.
- The exact adapter for the existing report-building application.

## Out of scope

- Excel report generation as a built-in workflow.
- Dashboard analytics and visualization.
- Animated visuals and interactive presentation layers.
- TUI and web app surfaces for the first cut.
- Self-improvement loops, fine-tuning, autonomous code editing, and multi-agent infrastructure.
- Domain-specific readers and writers inside the core.