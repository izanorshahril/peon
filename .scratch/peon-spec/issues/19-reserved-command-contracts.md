# 19 - Reserved command contracts and honest feedback

**What to build:** Reserve useful future command names without pretending missing features work, and keep command inventory synchronized with implementation status.

**Blocked by:** none; issue 16 is complete

**Status:** complete

**Tracker label:** `complete`

## Reserved commands

- `/session` for list/resume/history
- `/compact` for context compaction
- `/export` for local conversation export
- `/share` for publishing/sharing
- `/copy` for latest-response clipboard action
- `/status` for provider/model/context diagnostics
- `/usage` for token/cost accounting
- `/thinking` for model reasoning policy
- `/theme` for appearance selection
- `/editor` for external editor composition
- `/undo` and `/redo` for reversible conversation mutations
- `/fork` and `/tree` for conversation branching
- `/skills` and `/extensions` for capability management
- `/reload` for dynamic capability refresh
- `/init` for project instruction setup

## Scope

- Add reserved entries to shared catalog with descriptions and candidate vocabulary from living inventory.
- Show Reserved state in palette.
- Return concise unavailable message when invoked.
- Link each future implementation issue from inventory when created.
- Never add no-op handlers.
- Keep source provenance tied to the verified findings in issue 20's research report; reserved status still does not imply implementation.

## Acceptance criteria

- Reserved commands are discoverable and visually distinct.
- Enter on reserved command does not mutate context/configuration or invoke provider.
- Feedback names command and says feature is not available yet.
- Help can separate available and reserved commands.
- Inventory and catalog status agree in tests or generated validation.

## Test seam

Test catalog status and command-boundary side effects. One renderer test proves Reserved hint appears.
