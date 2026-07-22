# 05 - Complete controller provider and settings flows

**What to build:** Put model selection, provider setup, settings, and logout
effects fully behind host-neutral controller interfaces.

**Blocked by:** 02 - Complete runtime events and shared serializers.

**Status:** ready-for-agent

- [ ] Controller imports app-owned config/provider modules, never CLI rendering
  helpers or Textual classes.
- [ ] `/model`, `/provider`, `/settings`, and `/logout` complete through typed
  intents, outcomes, and continuation responses.
- [ ] Provider discovery, validation, persistence, active-model switching,
  logout replacement, and reasoning capability behavior remain compatible.
- [ ] Selection/input requests use stable semantic option IDs and safe metadata.
- [ ] Continuation tokens are scoped and single-use; invalid, stale, replayed,
  or cross-session values fail without mutation.
- [ ] Secrets never enter runtime events, logs, traces, sessions, journals, or
  error text.
- [ ] Failed provider/config operations leave active and persisted state intact.
- [ ] Headless tests drive every full workflow without terminal input or widgets.
- [ ] Existing prompt, informational-command, and session-transition controller
  behavior remains green.
- [ ] Focused controller/config/provider tests, full pytest, mypy, and diff
  validation pass.
