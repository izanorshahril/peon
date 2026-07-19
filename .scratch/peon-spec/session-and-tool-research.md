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

## Pi parity research for the next implementation spec

**Research date:** 2026-07-18

The current Peon startup policy is not Pi-compatible. Peon resumes the newest
JSONL file on ordinary interactive startup. Pi creates a new session by
default; `-c`/`--continue` explicitly continues the most recent current-
project session, `-r`/`--resume` opens a session picker, and `--session`
opens a specific path or session ID. Pi also supports `--fork`, `--no-session`,
`--session-dir`, and `--name`. Print mode is explicit with `-p`/`--print` and
does not implicitly continue the newest durable session.

Relevant Pi sources:

- [CLI usage](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)
- [Session guide](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/sessions.md)
- [CLI argument parser](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/cli/args.ts)
- [Session manager](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/session-manager.ts)
- [Print mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/print-mode.ts)
- [Interactive mode](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/interactive/interactive-mode.ts)

Pi's print mode has separate text and JSON output contracts. Text mode emits
the final assistant response for a single-shot prompt. JSON mode emits
normalized lifecycle and agent events, including tool activity, so callers do
not need to parse interactive terminal decoration. Piped stdin is merged into
the initial prompt.

Pi's interactive renderer uses tool-specific renderers rather than exposing
raw function-call envelopes. Collapsed tool calls retain a compact action
label and useful target, while collapsed results hide full output and expose a
bounded preview or expansion hint. Tool output is separated from neighboring
assistant/thinking blocks with deliberate blank-line padding. Semantic theme
tokens distinguish thinking text, tool titles, paths/accents, tool output,
muted hints, success, and errors. `Ctrl+T` (or its configured equivalent)
rebuilds the transcript and shows `Thinking blocks: hidden` or
`Thinking blocks: visible` as a status notice. Global tool expansion updates
the startup header, loaded resources, and existing chat entries.

Relevant Pi rendering sources:

- [Tool execution component](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/interactive/components/tool-execution.ts)
- [Read renderer](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/tools/read.ts)
- [Bash execution component](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/interactive/components/bash-execution.ts)
- [Interactive toggle/status handlers](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/modes/interactive/interactive-mode.ts)

Pi's built-in coding tool contracts are:

- `read`: cwd-aware bounded reads with offsets/limits and continuation hints.
- `write`: cwd-contained create/overwrite with parent-directory creation.
- `edit`: exact unique replacement with diff-oriented rendering.
- `bash`: cwd-bound command execution with streamed output, timeout,
  cancellation, bounded/truncatable results, and exit status.

Peon should register the latter three through `extensions`, reuse the existing
cwd/exclusion policy, and keep process execution behind an injected
cancellable operation boundary so the agent loop remains provider-neutral.

Pi loads resources through a dedicated resource loader before constructing the
effective system prompt. It discovers user and project skills, keeps skill
metadata visible in a compact structured block, and relies on the model's
`read` tool to load full skill content progressively. It also discovers
`AGENTS.md`/`CLAUDE.md` context files from the global and applicable parent
directories, supports project/global `SYSTEM.md` and `APPEND_SYSTEM.md`, and
reports resource diagnostics. Project resources are subject to trust and can
be disabled with `--no-context-files` or `--no-skills`; explicit resource paths
remain separately configurable.

Relevant Pi resource sources:

- [Resource loader](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/resource-loader.ts)
- [System prompt builder](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/system-prompt.ts)
- [Skills loader](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/src/core/skills.ts)
- [Context-file documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)
- [Skills documentation](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)

Resolved decisions for Peon:

1. Ordinary launch will eventually create a new session; continuation will be
  explicit. Existing automatic-resume tests describe legacy behavior and must
  be updated when the session slice is implemented.
2. Session selection, print behavior, and resume-command formatting belong in
  `app`; session entries remain append-only and provider-neutral.
3. Tool presentation should hide raw function-call JSON when collapsed and use
  compact tool-specific remarks plus bounded output expansion.
4. Thinking visibility changes must emit a visible status notice and refresh
  both restored and streaming transcript blocks.
5. Write/edit/bash belong in `extensions`; cwd containment, excluded paths,
  timeout/cancellation, and bounded output are mandatory first contracts.
6. Skill/context/system-prompt discovery belongs in an application resource
  loader. The agent loop consumes the resulting effective system prompt and
  does not discover files itself.

The implementation-ready requirements and test seams are captured in
[Pi parity spec](pi-parity-spec.md). No implementation was made during this
research pass.