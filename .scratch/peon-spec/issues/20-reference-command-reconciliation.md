# 20 - Reconcile Pi, Tau, and OpenCode command references

**What to research:** Verify exact slash-command inventories and useful command-palette UX in Pi coding agent, Tau agent, and OpenCode, then update Peon's living inventory.

**Blocked by:** none

**Status:** complete (research only)

## Reference order

1. Pi is primary behavior/UI target.
2. Tau contributes useful minimal-agent commands absent from Pi.
3. OpenCode contributes useful terminal commands/UX absent from Pi.

## Scope when unblocked

- Record exact command names, descriptions, aliases, ordering, keyboard behavior, and availability from each source.
- Link each claim to inspected source location/commit.
- Compare verified inventory with Peon's canonical and reserved names.
- Prefer one canonical Peon name when projects use several names for same purpose.
- Keep alternate names as candidate search vocabulary shown in hints.
- Create implementation issues only for verified, useful gaps.
- Remove speculative reserved commands that lack product value after comparison.

## Result

The research is recorded in
[Slash Command Reference Research](../slash-command-reference-research.md).
It includes fixed-source links for Pi and Tau and file-specific source links
for the active OpenCode repository. No Peon implementation code was changed.

Key reconciled findings:

- Pi provides the command manifest and combined slash/file autocomplete model.
- Tau provides the strongest registry boundary, typed command results, explicit
	alias versus search-term semantics, and completion-first Enter behavior.
- OpenCode provides the strongest separation between slash commands and a
	broader keymap-backed command palette, plus fuzzy matching across descriptions,
	categories, keywords, and aliases.
- Peon should keep its own canonical names and availability states while using
	the verified upstream names as candidate vocabulary or migration aliases.

## Acceptance criteria

- [x] Living inventory marks each source row verified with commit/source location or explicitly absent.
- [x] No source-project behavior is claimed from memory.
- Canonical-name changes include compatibility migration.
- New feature issues exclude behavior already completed in issues 01–19.

## Notes

Do not apply `ready-for-agent` to this issue. It is a completed research gate,
not an implementation task. Issues 16-19 remain the implementation backlog.
