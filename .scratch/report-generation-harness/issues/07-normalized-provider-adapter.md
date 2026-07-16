# 07 — Normalized provider adapter

**What to build:** A normalized provider adapter that lets the minimal agent loop use an OpenAI-compatible base URL or GitHub Copilot login without exposing provider-specific transport and authentication details to the core.

**Blocked by:** 06 — Minimal agent loop and command boundary

**Status:** ready-for-agent

- [ ] The core can send normalized context and available tools and receive either a final response or a tool call.
- [ ] OpenAI-compatible base URL configuration is contained inside the provider adapter.
- [ ] GitHub Copilot login configuration is contained inside the provider adapter.
- [ ] Provider authentication, transport, and response-shape failures become clear provider errors.
- [ ] Focused tests use fake transports and do not require network access or credentials.
