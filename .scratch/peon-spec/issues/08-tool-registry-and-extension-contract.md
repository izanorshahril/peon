# 08 — Tool registry and extension contract

**What to build:** A small in-process extension boundary where tools and skills can register names, descriptions, input schemas, handlers, and optional lifecycle hooks without adding domain logic to the agent core.

**Blocked by:** 06 — Minimal agent loop and command boundary

**Status:** implemented

- [x] An extension can register a tool through a public registry seam.
- [x] A registered tool exposes a model-facing name, description, input schema, and callable handler.
- [x] Tool lookup and invocation errors are clear and do not leak registry internals.
- [x] A small skill or extension can register more than one related tool without modifying the core loop.
- [x] Focused tests exercise registration and invocation through public behavior.
