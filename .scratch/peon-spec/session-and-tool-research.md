# Session and Tool Research

**Living document:** update this note when session persistence, tool-call
protocols, or built-in filesystem tools change. Record new upstream findings
here before implementation work so later sessions do not need to repeat the
same research.

**Research date:** 2026-07-18

**Scope:** Peon's current session and tool-call behavior, plus first-party Pi
and Tau source patterns relevant to durable sessions and read-only filesystem
tools.

## Current Peon state

- `AgentContext` is an in-memory list of provider-neutral messages.
- `run_task` appends user, assistant tool-call, and tool-result messages during
  one process lifetime, then continues the provider loop until a final answer.
- The interactive TUIs restore the newest valid append-only JSONL session on
  startup. `PEON_SESSION_DIR` overrides the default `~/.peon/sessions` path.
- `/new` creates and switches to a fresh durable session; `/clear` remains a
  compatibility command that clears the active in-memory context.
- `word_count` is registered by the default application registry and its
  handler passes direct registry tests. End-to-end execution still depends on
  the provider returning a response that Peon's parser recognizes as a
  `ToolCall`.
- The fallback parser accepts a whole JSON response containing `tool_call` or
  `tool_calls` and normalizes a `final` envelope into plain assistant content.
- The default application registry includes cwd-bound, read-only `read`, `ls`,
  `find`, and `grep` tools with bounded output and continuation offsets.

## Pi findings

Pi's coding-agent package uses a `SessionManager` for append-only JSONL
conversation files. Entries have IDs and parent IDs, and a leaf identifies
the current conversation path. The manager supports creating a new session,
continuing the most recent session, opening a specific session, in-memory
sessions, and appending messages without rewriting prior entries.

Relevant sources:

- [Session guide](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md)
- [Session format](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/session-format.md)
- [Session manager](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)
- [Read tool](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)
- [Tool factory index](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/index.ts)

Pi's built-in `read` tool is provider-neutral and application-owned. It is
created for a working directory, validates/resolves paths, supports optional
line `offset` and `limit`, handles text and supported images, and reports
truncation with a continuation hint. Read-only bundles add `grep`, `find`, and
`ls`. Tool definitions and executors are separate from the reusable agent
loop, and tool execution has a call ID suitable for transcript and UI events.

## Tau findings

Tau keeps the pure agent loop independent of session-file locations and coding
tools. Its harness owns the in-memory transcript; the coding session wrapper
adds JSONL session storage and resume behavior. Tool execution appends a
structured tool result to the transcript before the next provider turn.

Relevant sources:

- [Pure agent loop](https://github.com/huggingface/tau/blob/main/src/tau_agent/loop.py)
- [Agent harness](https://github.com/huggingface/tau/blob/main/src/tau_agent/harness.py)
- [Session wrapper](https://github.com/huggingface/tau/blob/main/src/tau_coding/session.py)
- [Session tests](https://github.com/huggingface/tau/blob/main/tests/test_coding_session.py)
- [Coding tools](https://github.com/huggingface/tau/blob/main/src/tau_coding/tools.py)
- [Tool-call loop tests](https://github.com/huggingface/tau/blob/main/tests/test_agent_loop.py)
- [Phase 3 architecture](https://github.com/huggingface/tau/blob/main/dev-notes/architecture/phase-3-agent-loop.md)

Tau's read tool follows the same useful boundary: the coding layer creates a
cwd-bound tool with a JSON schema, bounded output, and `offset`/`limit`
continuation. The portable loop only knows how to execute a registered tool
and append its result.

## Decisions for Peon tickets

1. Establish a durable transcript/session boundary before adding several
   session commands. The first slice should prove that a prompt, assistant
   response, tool call, and tool result survive process restart and can be
   resumed.
2. Preserve Peon's current `agent`/`app` dependency direction. Session file
   format and local paths belong outside the portable loop; the loop should
   continue to accept an injected context or transcript owner.
3. Diagnose `word_count` through a provider-to-TUI contract test. The registry
   and loop already work with normalized `ToolCall` values, so the test must
   exercise the actual provider response shape and verify both tool execution
   and continuation.
4. Add `read` as the first cwd-bound filesystem tool. Start read-only with
   path validation, UTF-8 text, bounded output, and line offset/limit. Defer
   write/edit/shell tools until the read contract is stable.
5. Keep the fallback tool wrapper replaceable. Native structured tool calls
   remain preferred; text fallback parsing should be hardened only as needed
   by an observable provider compatibility test.

## Resolved implementation decisions

- Peon uses one append-only JSONL file per session under `PEON_SESSION_DIR`,
  with a default of `~/.peon/sessions`; the newest file is resumed.
- Session records serialize only provider-neutral messages, tool-call metadata,
  and tool results. Provider profiles and credentials remain in the separate
  provider configuration store.
- `/new` creates a new session file and leaves the previous file untouched.
- Fallback providers use compact JSON for assistant tool-call history and
  normalize `{"final":"..."}` into plain assistant content.
- Filesystem handlers return bounded diagnostic strings for invalid paths,
  unreadable files, and empty searches so the model can recover in the normal
  continuation loop.
- The default registry now includes `word_count`, `read`, `ls`, `find`, and
  `grep`; all filesystem tools share cwd containment and generated-directory
  exclusions.

## Deferred follow-up

- Branching parent IDs, session selection commands, fenced fallback JSON, and
  image-aware reads remain future extensions beyond the first linear session
  and text-file tool slice.