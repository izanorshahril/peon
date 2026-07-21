# 08 — Move provider and settings flows behind controller

**What to build:** Make provider connection, model selection, settings, and logout workflows host-neutral. The controller emits typed input or selection requests with safe continuation tokens; Textual owns pickers and form presentation but not provider/config effects.

**Blocked by:** 06 — Move informational commands behind controller.

**Status:** ready-for-agent

- [ ] `/model`, `/provider`, `/settings`, and `/logout` execute through controller intents without widgets or terminal input functions.
- [ ] Provider discovery and saved-provider/model choices are represented as semantic option data with stable IDs.
- [ ] Secret input requests never place entered secrets in runtime events, logs, traces, session files, or error text.
- [ ] Continuation tokens are single-use and reject stale, invalid, cross-session, or replayed responses without state mutation.
- [ ] Provider creation, validation, persistence, model switching, logout replacement, and reasoning capability behavior remain compatible.
- [ ] Reusable provider/tool/resource policy is separated from Textual-only colors, spacing, rendering, and shortcuts.
- [ ] Textual retains current nested settings, backtracking, picker search, password input, and focus behavior.
- [ ] Headless tests can drive complete provider/model/settings/logout workflows through intents and supplied responses.
- [ ] Provider failures return typed outcomes and do not leave partially updated active or persisted configuration.
- [ ] Focused controller/config/provider/Textual, full pytest, static typing, and diff validation pass.
