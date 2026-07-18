## Destination

Peon is a minimal, modular Python agent core. It should reproduce the useful center of Tau and Minion: a small task-to-model loop with compact context and clear provider boundaries. It should borrow Pi's extension shape so tools, skills, and domain integrations can be added without growing the core into an application framework.

Excel report generation is not a Peon workflow. The existing report-building application owns workbook read/write behavior; its components may later be exposed to Peon as tools, skills, or an extension.

## Current status

- Foundational issues 01–15 are complete. Keep them as implementation history.
- Active spec: [Peon Slash Command System](slash-command-spec.md).
- Living command vocabulary: [Slash Command Inventory](command-inventory.md).
- Active command implementation: complete for issues 16–19; keep these issue
	files as the design and acceptance history.
- Reference reconciliation issue 20 is complete as a research-only task; findings live in [Slash Command Reference Research](slash-command-reference-research.md).
- Do not reopen completed provider, persistence, model-switching, settings, or transcript-rendering work while implementing command cleanup.

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

## Completed foundation

- [Minimal core boundary](issues/01-minimal-core-boundary.md) — The core is a small task/context/provider/tool loop. It does not own report generation or any domain-specific reader/writer.
- [Extension boundary](issues/02-workbook-evidence-contract.md) — Excel read/write belongs to the existing report-building application and can later be wrapped as a Peon tool, skill, or extension. No workbook contract belongs in the core.
- [Provider surface](issues/03-provider-surface.md) — Use one normalized model/provider shape by default; keep OpenAI-compatible and GitHub Copilot compatibility inside provider adapters and split the surface only when necessary.
- [Tech stack choice](issues/04-tech-stack-choice.md) — Python first; Go only if single-binary deployment becomes the dominant constraint.
- [Loop and extension pipeline](issues/05-shared-justification-pipeline.md) — The shared loop ends at model response, tool-call dispatch, and compact context updates. Extension-specific behavior stays inside extensions.
- [Minimal agent loop and command boundary](issues/06-minimal-agent-loop-and-command-boundary.md) — Complete.
- [Normalized provider adapter](issues/07-normalized-provider-adapter.md) — Complete.
- [Tool registry and extension contract](issues/08-tool-registry-and-extension-contract.md) — Complete.
- [Tool-call continuation and compact context](issues/09-tool-call-continuation-and-compact-context.md) — Complete.
- [Extension guide and sample tool](issues/10-extension-integration-guide-and-sample-tool.md) — Complete.
- [Interactive TUI and provider configuration](issues/11-interactive-tui-and-provider-configuration.md) — Complete.
- [Provider discovery and interaction levels](issues/12-provider-discovery-and-interaction-levels.md) — Complete.
- [Persistent provider configuration](issues/13-persistent-provider-configuration.md) — Complete.
- [Pi-style provider selection and logout](issues/14-pi-style-provider-selection-and-logout.md) — Complete; later active-provider reuse supersedes startup picker wording.
- [Assistant transcript background](issues/15-assistant-transcript-background-and-trailing-bar.md) — Complete.

## Active command-system backlog

- [Shared slash command catalog and search](issues/16-shared-slash-command-catalog.md) — complete; shared behavior seam implemented in `src/peon/app/commands.py`.
- [Pi-style command palette navigation](issues/17-pi-style-command-palette-navigation.md) — complete; both shells consume catalog ordering and metadata.
- [Command surface cleanup and migration](issues/18-command-surface-cleanup-and-migration.md) — complete; canonical names and hidden compatibility aliases are active.
- [Reserved command contracts](issues/19-reserved-command-contracts.md) — complete; reserved entries provide honest unavailable feedback.
- [Reference command reconciliation](issues/20-reference-command-reconciliation.md) — complete research gate; no runtime code changed.

Recommended order: 16, then 17 and 18, then 19. Issue 20 runs later and may amend inventory without reopening completed work.

## Deferred by design

- Exact Pi/Tau/OpenCode command parity. The verified references inform Peon vocabulary and UX decisions but do not define Peon's implementation surface.
- Behavior behind reserved commands: sessions, compaction, export/share, usage, editor, undo/redo, branching, skill/extension management, reload, and project initialization.
- Extension discovery and packaging beyond current in-process registry.
- Web, dashboard, autonomous coding, self-improvement, and multi-agent behavior.
- Exact adapter for existing report-building application.

## Out of scope

- Excel report generation as a built-in workflow.
- Dashboard analytics and visualization.
- Animated visuals and interactive presentation layers.
- New web/fullscreen app surfaces.
- Self-improvement loops, fine-tuning, autonomous code editing, and multi-agent infrastructure.
- Domain-specific readers and writers inside the core.