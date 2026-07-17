# 11 - Interactive TUI and provider configuration

**What to build:** An interactive terminal session that configures a provider in-session and reuses the existing agent loop for multiple prompts.

**Blocked by:** 06 - Minimal agent loop and command boundary; 07 - Normalized provider adapter; 09 - Tool-call continuation and compact context; 10 - Extension integration guide and sample tool

**Status:** complete

- [x] Bare `peon` or `peon --tui` starts an interactive session.
- [x] The TUI configures OpenAI-compatible and GitHub Copilot providers without requiring provider flags.
- [x] Multiple prompts share one compact `AgentContext`.
- [x] `/provider`, `/tools`, `/clear`, `/help`, and `/quit` commands are available.
- [x] The application-owned registry and sample tool are available to the interactive loop.
- [x] One-shot CLI mode remains available for scripted requests.