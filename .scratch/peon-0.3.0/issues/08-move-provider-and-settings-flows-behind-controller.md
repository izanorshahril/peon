# 08 — Move provider and settings flows behind controller

**What to build:** Make provider connection, model selection, settings, and logout workflows host-neutral. The controller emits typed input or selection requests with safe continuation tokens; Textual owns pickers and form presentation but not provider/config effects.

**Blocked by:** 06 — Move informational commands behind controller.

**Status:** completed

- [x] `/model`, `/provider`, `/settings`, and `/logout` execute through controller intents without widgets or terminal input functions.
- [x] Provider discovery and saved-provider/model choices are represented as semantic option data with stable IDs.
- [x] Secret input requests never place entered secrets in runtime events, logs, traces, session files, or error text.
- [x] Continuation tokens are single-use and reject stale, invalid, cross-session, or replayed responses without state mutation.
- [x] Provider creation, validation, persistence, model switching, logout replacement, and reasoning capability behavior remain compatible.
- [x] Reusable provider/tool/resource policy is separated from Textual-only colors, spacing, rendering, and shortcuts.
- [x] Textual retains current nested settings, backtracking, picker search, password input, and focus behavior.
- [x] Headless tests can drive complete provider/model/settings/logout workflows through intents and supplied responses.
- [x] Provider failures return typed outcomes and do not leave partially updated active or persisted configuration.
- [x] Focused controller/config/provider/Textual, full pytest, static typing, and diff validation pass.
