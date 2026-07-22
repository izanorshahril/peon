# 06 - Finish thin Textual and host ownership

**What to build:** Make Textual presentation-only while preserving terminal UX
and explicit handling of complete runtime event vocabulary.

**Blocked by:** 04 - Unify tool and shell lifecycle events; 05 - Complete
controller provider and settings flows.

**Status:** ready-for-agent

- [ ] Textual dispatches prompt, command, continuation, session, shell, and
  cancellation intents rather than executing application effects.
- [ ] Provider/config persistence, tool policy, resources, and session mutation
  are absent from widget behavior.
- [ ] Router has explicit handlers for every known typed event plus safe
  diagnostic fallback for unknown events.
- [ ] Transcript text/thinking deltas reconcile with final message without
  duplication.
- [ ] Tool lifecycle, usage, errors, cancellation, and processing state render
  only from typed events.
- [ ] Widgets, focus, key bindings, layout, animation, worker scheduling,
  pickers, secret-input presentation, and transcript interaction remain Textual.
- [ ] Legacy session/tool callback paths and duplicated session/provider/settings
  branches are removed after parity tests pass.
- [ ] Host catalog does not advertise prompt-toolkit as available; explicit old
  selection returns actionable migration guidance.
- [ ] Existing transcript, keyboard, mouse, picker, settings, session, resource,
  and shell UX regressions stay green.
- [ ] Focused Textual/controller tests, full pytest, mypy, and diff validation
  pass.
