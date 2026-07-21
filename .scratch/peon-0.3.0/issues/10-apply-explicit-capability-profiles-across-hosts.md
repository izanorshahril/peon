# 10 — Apply explicit capability profiles across hosts

**What to build:** Give every hosted run an explicit, consistent capability profile. Task, print, JSONL, and Textual modes resolve the same `none`, `read-only`, `coding`, or exact custom tool set; embedded use remains capability-free unless its caller injects tools.

**Blocked by:** 05 — Dispatch prompts through SessionController.

**Status:** ready-for-agent

- [ ] `none` advertises and executes no model-callable tools.
- [ ] `read-only` exposes read, list, find, and grep and rejects mutation or shell calls.
- [ ] `coding` exposes read, write, edit, and bash consistently in task, print, JSONL, and Textual modes.
- [ ] `custom` exposes exactly selected registered tools and rejects stale or forged disabled calls.
- [ ] Embedded sessions default to no tools and continue accepting an exact injected executor.
- [ ] Sample tools are excluded from all production default profiles.
- [ ] Skills and context discovery remain independently configurable from tool profiles.
- [ ] Provider-facing tool definitions exactly match executable names and enabled policy.
- [ ] CLI options and settings report the active profile and retain clear mutation/shell risk messaging.
- [ ] Focused profile/host/tool-security, full pytest, static typing, and diff validation pass.
