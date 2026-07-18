# Slash Command Inventory

**Living document:** update whenever command name, candidate vocabulary, availability, or owning issue changes.

**Reference status:** Pi, Tau, and OpenCode were inspected on 2026-07-18. The
source details and UI findings are recorded in
[Slash Command Reference Research](slash-command-reference-research.md).
Upstream verification changes the candidate vocabulary and reserved-contract
notes below; it does not mark a Peon command implemented.

## Naming rules

- One purpose gets one canonical command.
- Candidate names help search and appear in compact hints; they do not create duplicate handlers.
- Available commands work now or are part of active implementation.
- Reserved commands are discoverable future contracts and must return honest unavailable feedback.
- Hidden compatibility names resolve old commands during migration but do not appear in primary list.
- Provider fields belong under `/settings`, not top-level command list.

## Primary command surface

| Canonical | Candidate names and search phrases | Target status | Purpose | Owner |
| --- | --- | --- | --- | --- |
| `/help` | `/commands`, shortcuts, command list | Available | Show commands and keyboard behavior | 16, 17 |
| `/new` | `/clear`, `/reset`, new session, clear conversation | Available | Start clean conversation context | 18 |
| `/model` | `/models`, switch model, list models, change provider | Available | List and switch saved provider/model choice | 18 |
| `/provider` | `/connect`, `/login`, add provider, account | Available | Add or connect provider profile | 18 |
| `/settings` | `/config`, preferences, options, provider settings | Available | Edit UI and saved-provider settings | 18 |
| `/tools` | functions, capabilities, tool list | Available | List registered tools | 18 |
| `/skills` | skill list, capabilities | Available | List discovered and registered skills | 17 |
| `/logout` | `/disconnect`, sign out, remove provider | Available | Remove saved provider credentials/profile | 18 |
| `/quit` | `/exit`, `/close`, `/q` | Available | Exit Peon | 18 |

## Reserved command surface

| Canonical | Candidate names and search phrases | Status | Intended purpose | Owner |
| --- | --- | --- | --- | --- |
| `/session` | `/sessions`, `/resume`, `/history` | Reserved | List, resume, and manage persistent sessions | 19 |
| `/compact` | summarize context, shrink context | Reserved | Compact active conversation context | 19 |
| `/export` | `/save`, export conversation | Reserved | Save conversation locally | 19 |
| `/share` | `/publish`, share conversation | Reserved | Publish or share conversation | 19 |
| `/copy` | copy response, clipboard | Reserved | Copy latest assistant response | 19 |
| `/status` | info, diagnostics, current model | Reserved | Show provider, model, context, and capability state | 19 |
| `/usage` | tokens, cost, accounting | Reserved | Show token and cost usage | 19 |
| `/thinking` | `/reasoning`, effort, reasoning level | Reserved | Change model reasoning policy | 19 |
| `/theme` | colors, appearance, style | Reserved | Select UI theme | 19 |
| `/editor` | edit prompt, external editor | Reserved | Compose prompt in external editor | 19 |
| `/undo` | revert message, undo turn | Reserved | Undo latest conversation mutation | 19 |
| `/redo` | restore message, redo turn | Reserved | Redo reverted conversation mutation | 19 |
| `/fork` | branch session, fork conversation | Reserved | Fork current conversation | 19 |
| `/tree` | branches, session tree | Reserved | Navigate conversation branches | 19 |
| `/extensions` | `/plugins`, extension list | Reserved | Inspect and manage extensions | 19 |
| `/reload` | refresh skills, refresh extensions | Reserved | Reload dynamic capabilities | 19 |
| `/init` | initialize project, instructions | Reserved | Create project-agent instructions | 19 |

## Hidden compatibility surface

These names remain temporarily resolvable but disappear from default suggestions. Settings retain all behavior.

| Existing command | Replacement |
| --- | --- |
| `/temperature` | `/settings` provider Config; future `/thinking` may expose model policy |
| `/reasoning` | `/settings` provider Config; candidate for `/thinking` |
| `/max-completion-tokens` | `/settings` provider Config |
| `/max-output-tokens` | `/settings` provider Config |
| `/max-tokens` | `/settings` provider Config |
| `/supports-tools` | `/settings` provider Config |
| `/supports-stream` | `/settings` provider Config |
| `/supports-chat-completions` | `/settings` provider Config |
| `/base-url` | `/settings` saved provider Config |
| `/api-key` | `/settings` saved provider Config |
| `/response-format` | `/settings` saved provider Config/Response |
| `/provider-name` | `/settings` saved provider Name |

## Search and hint contract

- Row format: canonical command, short description, compact candidate hint, availability when reserved.
- Example: `/new  Start new conversation  aka /clear, /reset`.
- Description words participate in search. Query `switch model` finds `/model`.
- Candidate command names participate in search. Query `/reset` finds `/new`.
- Exact canonical match outranks candidate and description matches.
- Exact aliases execute canonical command ID; candidate phrases only search unless promoted to compatibility alias.

## Reference reconciliation

| Reference | Inventory status | Next action |
| --- | --- | --- |
| Pi coding agent | Verified | Use the built-in manifest, combined autocomplete, and interactive selector behavior documented in [research](slash-command-reference-research.md#pi-findings) |
| Tau agent | Verified | Use the registry/result boundary, explicit alias-vs-search-term distinction, and completion state documented in [research](slash-command-reference-research.md#tau-findings) |
| OpenCode | Verified | Use the keymap projection, fuzzy command palette, and slash popover distinctions documented in [research](slash-command-reference-research.md#opencode-findings) |

Only verified additions should update source notes. Prefer Pi behavior where
available; add Tau/OpenCode improvements only where they provide a useful
registry or interaction distinction. Keep Peon's canonical names as the
product decision, and record upstream names as candidates or compatibility
aliases rather than creating duplicate purposes.

## Verified upstream vocabulary

| Peon purpose | Verified upstream vocabulary | Inventory treatment |
| --- | --- | --- |
| Start a new session | Pi `/new`; Tau `/new` with `clear` and `reset` search terms; OpenCode `/new` with `/clear` alias | Keep `/new`; `/clear` and `/reset` remain migration candidates, with executable alias status decided by issue 18 |
| Choose a model | Pi and Tau `/model`; OpenCode `/models` | Keep `/model`; keep `/models` as compatibility vocabulary |
| Add or authenticate a provider | Pi and Tau `/login`; OpenCode `/connect` | Keep Peon `/provider`; expose `/login` and `/connect` as candidates |
| Exit | Pi `/quit`; Tau `/quit` with `/exit` alias; OpenCode `/exit` with `/quit` and `/q` aliases | Keep `/quit`; `/exit`, `/q`, and Peon's `/close` are compatibility vocabulary |
| Session list/resume | Pi `/session` and `/resume`; Tau `/session` and `/resume`; OpenCode `/sessions` with `/resume` and `/continue` aliases | Keep reserved `/session`; retain `/resume`, `/sessions`, and `/continue` as candidates until implementation defines the split |
| Context compaction | Pi `/compact`; Tau `/compact`; OpenCode `/compact` with `/summarize` alias | Keep reserved `/compact`; `/summarize` is a verified candidate |
| Theme selection | Tau `/theme`; OpenCode `/themes`; Pi exposes the flow through `/settings` | Keep reserved `/theme`; `/themes` is a verified candidate |
| Thinking controls | OpenCode `/thinking` controls visibility; Pi and Tau expose related controls through keybindings or other flows | Keep reserved `/thinking`; do not infer model-policy semantics |

These rows are research evidence, not a request to expand the current
implementation scope automatically.
