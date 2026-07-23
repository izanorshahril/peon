# Peon Agent Instructions

## Boundaries

- `agent`: provider-neutral messages, loop, events, execution contracts; never
  imports `app` or concrete integrations.
- `ai`: provider authentication, transport, serialization, normalization.
- `app`: CLI/TUI, configuration, sessions, resources, presentation policy.
- `extensions`: executable tools, skills, hooks, and registration.
- Keep provider quirks in adapters and domain behavior outside core runtime.
- Do not add unrelated autonomous, office, RAG, fine-tuning, dashboard, or
  communication features without an extension boundary and concrete need.

## Work

- Start at smallest owning abstraction; prefer existing public contracts.
- Use `uv run`; add focused tests beside changed behavior, then run full pytest
  and `uv run mypy src/peon` when source changes.
- Preserve unrelated worktree changes and avoid broad refactors.