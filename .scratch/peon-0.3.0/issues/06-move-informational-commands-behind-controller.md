# 06 — Move informational commands behind controller

**What to build:** Make informational slash commands execute through host-neutral controller intents and typed outcomes. A headless caller and Textual receive the same help, tool, skill, session, and reasoning information without duplicating command effects.

**Blocked by:** 05 — Dispatch prompts through SessionController.

**Status:** ready-for-agent

- [ ] The controller resolves and executes `/help`, `/tools`, `/skills`, `/session`, and `/reasoning` without importing a host.
- [ ] Command argument validation and availability behavior match the shared command catalog.
- [ ] Command outcomes contain semantic data suitable for plain text, Textual, or future RPC presentation rather than preformatted widget objects.
- [ ] Tool outcomes identify registered and enabled state from controller-owned policy.
- [ ] Skill outcomes distinguish discovered, registered, and progressively loaded skills without injecting a body twice.
- [ ] Session outcomes expose current durable or in-memory identity and compatible message/usage facts.
- [ ] Reasoning outcomes preserve provider capability checks and active-state updates.
- [ ] Textual renders outcomes with current user-visible behavior; a headless test can execute every command without Textual.
- [ ] Prompt-toolkit behavior remains temporarily compatible until its retirement ticket.
- [ ] Focused command/controller/Textual, full pytest, static typing, and diff validation pass.
