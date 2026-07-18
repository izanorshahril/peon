# 16 - Shared slash command catalog and search

**What to build:** Replace duplicated command metadata and prefix matching with one shared command catalog used by both terminal shells.

**Blocked by:** none; issues 01–15 are completed foundation

**Status:** complete

**Tracker label:** `complete`

## Scope

- Define stable command IDs independent of display names and aliases.
- Store canonical name, candidate names, concise description, search terms, availability, argument policy, and display order.
- Support `available`, `reserved`, and `hidden-compatibility` availability.
- Normalize slash, case, hyphens, underscores, punctuation separators, and whitespace.
- Rank exact canonical, canonical prefix, exact candidate, candidate prefix, all-token, then description/search-term matches.
- Keep deterministic catalog order for equal scores.
- Parse arguments only after exact canonical or compatibility-alias resolution.
- Return typed search matches and typed command invocation.
- Make both prompt-toolkit completion and Textual palette consume catalog results.

## Acceptance criteria

- One command definition drives names/descriptions in both shells.
- Searching `reset` returns canonical `/new`.
- Searching `switch model` returns `/model` through description/search terms.
- Exact `/model` ranks before `/models` compatibility vocabulary.
- Hidden compatibility aliases resolve but do not appear in default suggestions.
- Reserved commands are identified in match metadata.
- Unknown slash input remains unknown and cannot become agent chat input.
- Existing available command behavior remains unchanged until issue 18 migrates names.

## Test seam

Test public command-catalog search and resolution. Renderer tests only prove each shell consumes returned order and metadata.
