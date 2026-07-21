# 07 — Move session transitions behind controller

**What to build:** Make new, resume, and fork session workflows execute through controller intents and typed outcomes. Textual renders controller-provided choices and state while headless callers can drive identical transitions without widgets or terminal input.

**Blocked by:** 06 — Move informational commands behind controller.

**Status:** ready-for-agent

- [ ] `/new`, `/resume`, and `/fork` execute through controller intents without host imports.
- [ ] New sessions preserve empty-session cleanup, fresh context, resource reapplication, and usage reset behavior.
- [ ] Resume selection exposes stable option IDs, prompt summaries, interaction counts, ages, names, and current-session exclusion as semantic data.
- [ ] Fork preserves parent metadata, canonical conversation messages, resources, and optional name behavior.
- [ ] Selection uses a single-use continuation token; stale, invalid, or reused tokens fail without state mutation.
- [ ] Durable and in-memory stores work through the same controller interface.
- [ ] Existing 0.2 session files load and transition without migration.
- [ ] Textual retains current picker, search, focus, row layout, and resume-command behavior.
- [ ] Headless tests complete new/resume/fork workflows entirely through intents and outcomes.
- [ ] Focused controller/session/Textual, full pytest, static typing, and diff validation pass.
