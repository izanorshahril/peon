# Peon Agent Instructions

These instructions apply to Peon and projects that use this workspace as their
agent foundation.

## Product Priority

1. Mimic Pi coding-agent first for the user experience.
2. Use Tau coding-agent as the primary Python implementation reference.
3. Use Minion for compact-context and local-model resilience ideas.
4. Treat Hermes, OpenClaw, Odysseus, Unsloth, Goose, Open WebUI, Zed, and
   OpenCode as optional references for later capabilities, not as reasons to
   expand Peon's core prematurely.

The Pi-first rule applies especially to the UI and interaction model. A new
feature should feel like a focused terminal coding harness before it feels like
a dashboard, enterprise console, or general-purpose assistant.

## Pi-First UX

- Keep the conversation as the primary surface: transcript above, composer at
  the bottom, and minimal persistent chrome.
- Prefer Pi-like interaction patterns for startup guidance, slash commands,
  model switching, queued messages, cancellation, sessions, and tool output.
- Keep interactive, print, JSON, RPC, and embedded usage as distinct modes when
  adding frontends.
- Make the TUI readable, keyboard-oriented, selectable, and useful in a plain
  terminal. Do not add decorative UI that competes with the transcript.
- Keep provider, model, context, and usage status compact and out of the
  conversation unless the user explicitly asks for details.
- Prefer extension points for commands, skills, tools, themes, and integrations
  over adding unrelated features to the agent loop.

## Python Architecture

- Keep `agent` portable and provider-neutral. It owns messages, tools, the loop,
  events, and the harness; it must not import `app` or concrete integrations.
- Keep provider authentication, transport, request serialization, and response
  normalization inside `ai` adapters.
- Keep application policy, configuration, CLI, TUI, and presentation in `app`.
- Keep executable capabilities and their registration in `extensions`.
- Prefer Tau's small-layer, typed-contract approach when implementing Python
  features, while preserving Peon's smaller public surface.
- Use `uv run` for Python commands and keep focused tests beside each changed
  boundary.

## Provider Compatibility

- Send `User-Agent: peon` on every outbound provider request so ai-bridge can
  identify Peon traffic.
- Use native provider tool calling whenever the endpoint supports it.
- When native tools are unavailable, use the ai-bridge-compatible text bridge by
  default: append a tool instruction message after the conversation, use the
  `developer` role by default, and emit the compact JSON `tool_call` envelope.
- Keep the fallback role configurable between `developer` and `system`. Do not
  assume that every model gives either role the same priority.
- Parse the fallback JSON envelope back into the provider-neutral `ToolCall`
  contract so the normal agent executor can continue the turn.
- Keep the wrapping strategy replaceable. Do not make the current message
  bridge the only future option; native fields, role-based prompts, structured
  response modes, and other provider adapters may coexist.
- Preserve provider-specific quirks in adapters and tests. The agent loop should
  not branch on OpenAI, ai-bridge, Copilot, or model-vendor details.

## Change Discipline

- Start at the smallest owning abstraction and form a falsifiable local
  hypothesis before editing.
- Prefer the existing public contracts and the smallest focused change.
- Add or update focused tests for request payloads, response parsing, and
  user-visible behavior when those surfaces change.
- Do not add self-improvement, autonomous coding, office workflows, image
  generation, fine-tuning, RAG, or communication channels to the core without a
  clear extension boundary and a concrete product need.

## Living Research

- Keep session and filesystem-tool findings in
  `.scratch/peon-spec/session-and-tool-research.md`.
- Update that note with local behavior, primary Pi/Tau source links, and
  resolved decisions before implementing session persistence or new tools.
- Treat the note as the continuity point for future sessions; do not repeat an
  upstream crawl when the existing source snapshot still answers the question.

## Reference Projects

- Pi coding agent: https://github.com/earendil-works/pi/tree/main/packages/coding-agent
- Tau: https://github.com/huggingface/tau
- Minion: https://github.com/Sentdex/minion
- Hermes Agent: https://github.com/NousResearch/hermes-agent
- OpenClaw: https://github.com/openclaw/openclaw
- Odysseus: https://github.com/odysseus-dev/odysseus
- Unsloth: https://github.com/unslothai/unsloth
- Goose: https://github.com/aaif-goose/goose
- Open WebUI: https://github.com/open-webui/open-webui
- Zed: https://github.com/zed-industries/zed
- OpenCode: https://github.com/anomalyco/opencode