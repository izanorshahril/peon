# 09 — Move bang-shell behavior behind controller

**What to build:** Execute direct visible and hidden shell commands through a host-neutral controller intent. Textual retains command-entry and rendering behavior while tool execution, cancellation, events, and optional model-context injection are shared with future hosts.

**Blocked by:** 05 — Dispatch prompts through SessionController.

**Status:** completed

- [x] A direct shell intent validates command text and bash availability before execution.
- [x] Visible shell execution emits tool lifecycle events and submits one canonical model-following prompt containing the bounded result.
- [x] Hidden shell execution emits progress/result events but does not add shell output to model conversation context.
- [x] Tool timeout, output bounds, live output, cancellation, cwd containment, and process-tree termination remain compatible.
- [x] Direct shell results are not accidentally persisted as provider tool messages unless they enter a model-following turn by declared policy.
- [x] Textual `!` and `!!` syntax, compact output, expansion, focus, and cancellation remain compatible.
- [x] A headless caller can execute both shell modes through controller intents without Textual.
- [x] Shell errors produce one typed terminal outcome and do not trigger a provider request.
- [x] Prompt-toolkit remains temporarily compatible until retirement.
- [x] Focused controller/bash/Textual, full pytest, static typing, and diff validation pass.
