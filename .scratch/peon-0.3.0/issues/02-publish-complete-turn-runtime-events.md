# 02 — Publish complete-turn runtime events

**What to build:** Let a headless caller observe one complete, non-streaming prompt turn as ordered immutable runtime events and serialize those events through one shared versioned dictionary interface. Existing JSONL consumers retain schema version 1 behavior while schema version 2 exposes common metadata and precise lifecycle facts.

**Blocked by:** 01 — Freeze 0.2.0 baseline and contracts.

**Status:** completed

- [x] A successful no-tool prompt emits exactly one turn start, canonical user and assistant message events, and exactly one terminal turn event.
- [x] Provider failure, cancellation, and persistence failure each still emit exactly one terminal turn event with a structured result.
- [x] Every public event carries deterministic correlation, timestamp, and run-scoped sequence metadata using injected clocks and IDs.
- [x] One pure serializer converts typed events to standard Python dictionaries.
- [x] Schema version 1 records remain compatible with the characterized JSONL output and remain the CLI default.
- [x] Schema version 2 represents the complete non-streaming lifecycle without host-specific fields.
- [x] JSONL output uses the shared serializer instead of a private host translation.
- [x] Normal session files still contain canonical messages only, not lifecycle events.
- [x] Existing callback and result interfaces continue to work during migration.
- [x] Focused event, CLI JSONL, persistence, full pytest, static typing, and diff validation pass.
