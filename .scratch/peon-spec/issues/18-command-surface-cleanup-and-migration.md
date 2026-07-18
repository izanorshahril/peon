# 18 - Command surface cleanup and compatibility migration

**What to build:** Replace noisy per-field commands with small task-oriented command surface while preserving old vocabulary through hidden compatibility aliases.

**Blocked by:** none; issue 16 is complete

**Status:** complete

**Tracker label:** `complete`

## Canonical available surface

- `/help`
- `/new`
- `/model`
- `/provider`
- `/settings`
- `/tools`
- `/logout`
- `/quit`

## Migration decisions

- `/clear` and `/reset` map to `/new`.
- `/models` maps to `/model`; model picker already lists all saved provider/model choices.
- `/exit`, `/close`, and `/q` map to `/quit`.
- `/connect` and `/login` search for `/provider`; promotion to executable aliases depends on argument ambiguity tests.
- `/config` and `preferences` search for `/settings`.
- Provider field commands become hidden compatibility aliases and disappear from primary suggestions.
- `/provider-name` behavior remains in `/settings` under saved provider Name.
- Temperature, reasoning, token limits, support flags, base URL, API key, and response format remain under saved provider Config/Request/Response settings.

## Acceptance criteria

- Primary palette contains only task-oriented available commands plus clearly marked reserved commands.
- Current settings functionality remains reachable.
- Old exact field commands continue working during migration but are hidden.
- `/new` clears context and transcript using existing clear behavior.
- `/model` handles list and switch behavior currently split across `/models` and `/model`.
- Help output comes from shared catalog, not hand-written command strings.
- README and living inventory use canonical names.

## Test seam

Exercise commands through command boundary with fake provider/config store. Assert stable command IDs and visible behavior, not private handler layout.
