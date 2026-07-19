# Pi Parity: Sessions, Transcript Presentation, Coding Tools, and Resources

## Problem Statement

Peon currently behaves like an early linear-session agent while its product direction is Pi-first. Several user-visible behaviors and coding-agent capabilities therefore diverge from Pi in ways that make Peon harder to predict and less useful for real coding work:

- An ordinary Peon launch automatically resumes the newest JSONL session. Pi starts a new interactive session by default; continuation is explicit with `-c`/`--continue`, session browsing is explicit with `-r`/`--resume`, and a concrete session can be selected with `--session`.
- Peon has no explicit session-selection, branching, ephemeral-session, or print/export contract. Its non-interactive path prints only a final response and does not expose Pi's distinction between text output and event-oriented output.
- Collapsed tool blocks expose implementation-shaped function-call details and use generic output text. Tool, thinking, and assistant blocks do not yet have a consistent Pi-like spacing and semantic color treatment.
- `Ctrl+T` changes thinking visibility but gives no visible confirmation, so an operator cannot tell which state is active without opening settings.
- The default tool set is read-only. Peon does not yet provide safe `write`, `edit`, or `bash` capabilities for ordinary coding tasks.
- Skill discovery currently returns names only. Skill instructions are not loaded into the resource model, and Peon has no automatic system-prompt or `AGENTS.md`/`CLAUDE.md` context-file loader comparable to Pi.

These are related Pi-parity gaps, but they cross distinct ownership boundaries. The implementation must preserve Peon's provider-neutral agent loop, keep application policy in `app`, keep executable capabilities in `extensions`, and avoid importing Pi's entire feature surface merely to imitate its vocabulary.

## Solution

Add a staged Pi-parity capability set behind existing application and extension seams:

1. Make startup session choice explicit and add a Pi-shaped CLI contract for continue, resume, specific-session selection, ephemeral sessions, branching, and print mode. Ordinary interactive startup creates a fresh session. The most recent session is continued only when requested.
2. Upgrade the session representation from a purely linear latest-file policy toward append-only entries with stable session identity, parent relationships, and a selectable active leaf. Keep old session files readable and provide a deliberate migration or compatibility path.
3. Introduce a transcript presentation model that renders compact tool remarks, hidden/expanded tool results, thinking blocks, status notices, and assistant text as separate semantic blocks. Match Pi's observable spacing and color hierarchy while retaining Peon's existing Textual and classic-shell surfaces.
4. Make `Ctrl+T` update the persisted setting and immediately emit a status notice such as `Thinking blocks: hidden` or `Thinking blocks: visible`.
5. Add cwd-bound `write`, exact-replacement `edit`, and cancellable `bash` tools to the default extension registry. Keep path validation, excluded-directory policy, bounded output, and provider-neutral tool contracts at the extension boundary.
6. Add an application-owned resource loader that discovers and loads system prompt sources, append-system instructions, project/user context files, and skills. Put only compact skill metadata in the system prompt by default; load complete skill instructions progressively through the existing read/tool path or an explicit skill invocation.
7. Show loaded-resource diagnostics in startup/help surfaces without leaking provider-specific implementation details into the agent loop.

The target is behavioral parity for the chosen Peon surface, not a claim that every Pi command or renderer is implemented. Features not needed to support these contracts remain reserved for later specifications.

## User Stories

1. As an operator, I want an ordinary Peon launch to start a fresh interactive session, so that an old conversation never appears unexpectedly.
2. As an operator, I want `peon -c`/`peon --continue` to continue the most recent session for the current working directory, so that resuming work is explicit and fast.
3. As an operator, I want `peon -r`/`peon --resume` to browse available sessions, so that I can choose a prior task instead of accepting whichever file is newest.
4. As an operator, I want to open a session by path or stable identifier, so that scripts and printed resume instructions can return to an exact conversation.
5. As an operator, I want the application to reject conflicting session-selection flags clearly, so that startup never silently chooses an unintended session.
6. As an operator, I want `--no-session` to run without writing durable conversation state, so that one-off or sensitive tasks can remain ephemeral.
7. As an operator, I want a session name to be assigned at startup, so that related work is easy to identify in a session picker.
8. As an operator, I want `/new` to create a fresh session without deleting the previous one, so that starting over preserves history.
9. As an operator, I want a clear resume command at shutdown when the session is durable, so that I can return to the exact conversation later.
10. As an operator, I want session browsing to remain scoped to the current project by default, so that unrelated conversations do not crowd the picker.
11. As an operator, I want an explicit all-session or cross-project path only when requested, so that project context and trust boundaries remain understandable.
12. As an operator, I want to fork a previous session into a new session, so that experimentation does not mutate the original conversation path.
13. As an operator, I want session entries to retain parent relationships, so that branches can be displayed and resumed deterministically.
14. As an operator, I want the active conversation leaf to be unambiguous after a restart, so that the visible transcript matches the selected branch.
15. As an operator, I want legacy linear JSONL sessions to remain readable, so that an upgrade does not strand existing conversations.
16. As an operator, I want `-p`/`--print` to process a prompt and exit, so that Peon can be composed in scripts and pipelines.
17. As an operator, I want print text mode to emit the final assistant response without interactive decoration, so that command output is machine-friendly.
18. As an operator, I want print mode to accept piped standard input as prompt material, so that commands such as `type README.md | peon -p "Summarize this"` work on Windows and equivalent shells.
19. As an operator, I want an event or JSON-lines output mode, so that integrations can observe assistant, thinking, tool-call, tool-result, and lifecycle events without scraping terminal text.
20. As an operator, I want print mode session behavior to be explicit, so that a one-shot command does not accidentally continue an unrelated durable session.
21. As an operator, I want collapsed tool output to show a short human-readable remark, so that the transcript is scannable.
22. As an operator, I do not want collapsed tool blocks to expose serialized function names, JSON arguments, or provider-shaped envelopes, so that implementation details do not dominate the conversation.
23. As an operator, I want compact remarks to identify the action and relevant target, so that `read`, `write`, `edit`, and `bash` remain distinguishable at a glance.
24. As an operator, I want an expansion hint on content that has hidden output, so that I can discover how to inspect details.
25. As an operator, I want `Ctrl+O` to expand or collapse tool results consistently across restored and newly streamed messages, so that visibility is a global presentation choice.
26. As an operator, I want tool output previews to be bounded, so that a large command result does not push the composer off-screen.
27. As an operator, I want full tool output to remain available when expanded, subject to safety and truncation limits, so that debugging information is not lost.
28. As an operator, I want a blank-line separation after assistant, thinking, and tool output blocks where Pi uses it, so that adjacent events do not visually merge.
29. As an operator, I want thinking blocks to use a distinct muted or thinking color, so that internal reasoning is visually separate from final answers.
30. As an operator, I want tool calls and tool results to use semantic tool colors, so that action, output, success, and error states can be distinguished without reading every line.
31. As an operator, I want styling to be consistent between Textual and the classic shell, so that changing frontends does not change the transcript's meaning.
32. As an operator, I want `Ctrl+T` to immediately report `Thinking blocks: hidden` when hiding reasoning, so that the current state is obvious.
33. As an operator, I want `Ctrl+T` to immediately report `Thinking blocks: visible` when showing reasoning, so that the current state is obvious.
34. As an operator, I want the toggle status to appear as a transient transcript/status notice rather than requiring settings navigation, so that the shortcut is self-explanatory.
35. As an operator, I want the thinking visibility setting to remain persisted across restarts, so that my preferred transcript density is stable.
36. As an operator, I want `write` to create or replace a cwd-contained file, so that the agent can create source files and documentation.
37. As an operator, I want `write` to create missing parent directories only within the working directory, so that normal project structure can be created without path escape.
38. As an operator, I want writes to report a concise success summary, so that I know what changed without dumping the entire file.
39. As an operator, I want writes to reject excluded or sensitive paths, so that default tools do not modify generated credentials or protected state.
40. As an operator, I want `edit` to replace an exact unique text match, so that an edit cannot silently alter the wrong occurrence.
41. As an operator, I want `edit` to fail with a useful diagnostic when the old text is absent or ambiguous, so that the agent can recover by rereading the file.
42. As an operator, I want `edit` to show a compact diff or changed-line summary, so that the mutation is auditable in the transcript.
43. As an operator, I want `edit` to share the same cwd and excluded-path policy as `read` and `write`, so that all filesystem tools have one safety model.
44. As an operator, I want `bash` to execute in the configured working directory, so that commands operate on the project I opened.
45. As an operator, I want `bash` output to stream while a command runs, so that a long-running command is visibly active.
46. As an operator, I want `bash` to support timeout and cancellation, so that a stalled command does not block the agent indefinitely.
47. As an operator, I want `bash` to return stdout, stderr, exit status, and cancellation state in a structured result, so that the model can decide what to do next.
48. As an operator, I want large `bash` output to be truncated with a clear continuation or full-output notice, so that useful diagnostics remain available without overwhelming context.
49. As an operator, I want the collapsed `bash` remark to show a safe command summary rather than raw tool-call JSON, so that the action is understandable and compact.
50. As an operator, I want mutation and shell tool results to survive session persistence, so that a resumed transcript explains what happened before restart.
51. As an operator, I want Peon to discover skills from supported project and user locations, so that reusable instructions are available without manual registration.
52. As an operator, I want the system prompt to list skill names, descriptions, and locations without injecting every skill body, so that context remains compact.
53. As an operator, I want a matching skill's full instructions to be loaded when needed, so that specialized workflows can guide the agent without always consuming context.
54. As an operator, I want explicit skill invocation to load the requested instructions, so that I can force a known workflow even when semantic matching is uncertain.
55. As an operator, I want malformed or unreadable skills to produce diagnostics rather than aborting unrelated startup, so that one bad resource does not hide all capabilities.
56. As an operator, I want `AGENTS.md` and compatible context files discovered from the current directory and applicable parents, so that project conventions are automatically available.
57. As an operator, I want global context instructions loaded in addition to project instructions, so that personal coding policy and repository policy can coexist.
58. As an operator, I want context-file order and precedence to be deterministic, so that a restart cannot change which instruction wins.
59. As an operator, I want context files and skills to respect project trust and opt-out settings, so that local instructions are not executed or loaded blindly.
60. As an operator, I want a configurable system prompt file and append-system prompt file, so that deployment-specific behavior does not require Python changes.
61. As an operator, I want `--no-context-files`, `--no-skills`, and equivalent controls where practical, so that resource loading can be disabled for controlled runs.
62. As an operator, I want startup/help surfaces to identify loaded skills, prompts, and context files, so that I can diagnose why the agent behaves a certain way.
63. As an extension author, I want resource loading to remain separate from the portable agent loop, so that providers and core message execution stay reusable.
64. As an extension author, I want `write`, `edit`, and `bash` to use the same registry contract as existing tools, so that custom tools can share invocation and lifecycle behavior.
65. As a maintainer, I want one session-selection service used by CLI startup, interactive `/resume`, and print mode, so that session policy cannot diverge across entry points.
66. As a maintainer, I want one transcript block model used by restored and live messages, so that presentation does not depend on whether a message just streamed.
67. As a maintainer, I want tool rendering to depend on normalized tool metadata and result state, so that provider-specific envelopes never reach the UI.
68. As a maintainer, I want filesystem safety checks centralized, so that new mutation tools cannot accidentally bypass read-only path policy.
69. As a maintainer, I want shell execution isolated behind a cancellable operation boundary, so that platform-specific process behavior does not leak into the agent loop.
70. As a maintainer, I want resource diagnostics to be observable through tests and startup state, so that missing instructions are distinguishable from intentionally disabled instructions.
71. As a maintainer, I want old tests that assert automatic latest-session resume updated to the new explicit policy, so that the suite describes the intended product rather than preserving accidental behavior.
72. As a maintainer, I want the feature split into session, presentation, tool, and resource sub-slices behind stable contracts, so that later implementation can land incrementally without one risky rewrite.

## Implementation Decisions

- Treat ordinary interactive startup as `create`, not `continue`. Reserve `continue` for an explicit `-c`/`--continue` request. Keep `/new` as an in-session fresh-session action.
- Add a session-selection service in the application layer. It owns create, continue-recent, resume-by-selection, open-by-path or ID, ephemeral mode, and fork decisions. The agent loop receives an injected transcript/session owner and remains unaware of CLI flags.
- Preserve append-only JSONL storage. Add a durable session header, stable entry IDs, parent IDs, timestamps, working-directory metadata, and an active-leaf interpretation. Do not rewrite an existing conversation to create a branch; append or copy into a new session according to the selected operation.
- Define explicit compatibility behavior for the existing version-1 linear JSONL format. Legacy files must be loadable as a single linear branch, with deterministic synthetic IDs where needed. Migration must be opt-in or lossless and must not delete user data.
- Scope automatic session listing to the current working directory. A separate cross-project selection path may expose other sessions only with an explicit user action and must surface the source working directory.
- Introduce CLI flags for continue, resume, specific session, fork, no-session, session directory, session name, print, and structured event output. Validate mutually exclusive flags before provider startup. Keep the current provider/model/reasoning flags intact.
- Define print text mode as single-shot output: accept an initial prompt and optional piped stdin, run the agent, and write the final assistant text without interactive header/footer/status decorations. Define JSON-lines mode as one normalized event per line, including session lifecycle, assistant text, thinking, tool-call, tool-result, and error events.
- Make print-mode persistence explicit. A print invocation creates an ephemeral session by default unless the caller explicitly selects continuation or a durable session. Never resume the newest file implicitly in a one-shot command.
- Add a resume-command formatter for durable interactive sessions. It should use a stable session ID when the default session directory is active and include the custom directory when necessary.
- Replace the current tuple-only transcript rendering decision with a semantic block model that can represent role, tool name, compact remark, output preview, expanded output, status, error state, and visibility state. Keep persisted message data provider-neutral.
- Render collapsed tool blocks as concise human-readable remarks and an expansion hint. Never display raw serialized function-call JSON or provider-specific argument envelopes in the collapsed presentation. Tool-specific compact labels may include a safely shortened path, command, line range, line count, or status.
- Render tool results collapsed by default with bounded previews or no preview when the tool defines a compact remark. Expanded mode reveals the complete bounded result and truncation metadata. The global expansion action must update restored and active blocks together.
- Make spacing a transcript contract: insert a deliberate spacer between adjacent semantic sections, avoid duplicate blank lines when a renderer already owns padding, and ensure assistant text, thinking, tool call, and tool result transitions have stable visual separation.
- Replace generic role-only styling with semantic presentation tokens for thinking, tool title, tool output, accent/path, muted hint, success, and error. Keep colors configurable by the application theme and apply the same tokens in Textual and classic-shell renderers.
- On every thinking-visibility toggle, update the persisted setting, refresh existing and streaming blocks, and emit a status notice with the exact current state. Status notices should use the existing application status channel rather than becoming model messages.
- Register `write`, `edit`, and `bash` through the extension registry using provider-neutral schemas and structured execution results. Existing `read`, `ls`, `find`, and `grep` remain available.
- `write` accepts a relative or cwd-contained path and text content, creates missing in-scope parents, rejects excluded paths, and reports bytes/lines written. It must not follow a path outside the working directory through absolute paths, traversal, or symlink escapes.
- `edit` accepts a cwd-contained path, an exact old-text value, and replacement text. It succeeds only when the old text occurs exactly once, writes atomically where practical, and returns a compact diff-oriented result. Ambiguous, missing, invalid, or excluded targets are errors.
- `bash` accepts a command and optional timeout. It runs in the configured cwd through a platform-aware subprocess boundary, captures stdout/stderr with bounded accumulation, exposes cancellation, terminates the process tree where supported, and returns exit/cancel/truncation metadata. No shell command filtering is promised by this spec; cwd, environment, timeout, and output policy are the safety boundary.
- Preserve the existing generated/sensitive-directory exclusion policy for all filesystem mutation tools. Make the policy shared rather than copied into each handler.
- Extend persisted tool-result metadata sufficiently to restore compact rendering, expanded rendering, status, and truncation notices after restart without rerunning a command.
- Add an application-owned resource loader with typed results and diagnostics for skills, prompt templates, system prompt sources, append-system prompt sources, and context files. Loading failures are reported as diagnostics and do not silently become empty success.
- Discover user and project skills using the existing `.agents/skills` convention and compatible Peon locations. Parse metadata and retain full content plus the skill directory for relative-reference resolution. Project-local executable or instruction resources must be subject to an explicit trust policy.
- Format model-visible skill metadata in a compact XML-like or otherwise structured section that names the skill, describes when it applies, and identifies its absolute source location. Do not place every full skill body in the base system prompt.
- Load `AGENTS.md` and compatible context files from applicable parent directories and the current working directory, plus global instructions where configured. Preserve deterministic ordering and expose the loaded source paths to startup diagnostics.
- Support system-prompt replacement and append sources from configured files or literal values. Explicit CLI values take precedence over discovered defaults, and opt-out flags disable discovery without disabling explicitly supplied paths unless documented otherwise.
- Rebuild the effective provider request system prompt from tools, system prompt sources, context files, and model-visible skill metadata at session creation and explicit resource reload. The agent loop receives the resulting prompt but does not discover files itself.
- Keep resource inspection and reload commands separate from this implementation unless required by the new startup contract. Existing `/skills` may report discovered metadata; full skill command execution can be a follow-up slice if it cannot fit the first resource-loader implementation.
- Use existing application-level session, TUI, registry, filesystem safety, and provider seams. Do not add a second parallel session format, renderer-specific tool executor, or provider-specific resource loader.
- Implement in slices in this order: explicit session policy and print contract; semantic transcript rendering and toggle status; mutation/shell tools; resource loading and system-prompt assembly. Each slice must remain independently testable and shippable.

## Testing Decisions

- Test external behavior at the highest existing seam. Prefer CLI/session startup tests for session choice, public Textual application tests for transcript presentation, registry invocation tests for tools, and provider request tests for assembled system prompts.
- Session tests must cover ordinary startup creating a new session, explicit continue selecting the newest current-project session, explicit resume selecting a chosen session, specific session opening, no-session non-persistence, conflicting flag diagnostics, fork isolation, resume-command formatting, and legacy linear-file compatibility.
- Print tests must assert text-mode stdout contains only the final assistant response, piped input is incorporated, JSON mode emits parseable normalized events, tool events are included in order, and print mode does not implicitly resume a durable session.
- Transcript tests must assert collapsed blocks omit raw function-call serialization, include the compact action remark and expansion hint, preserve bounded previews, expose full bounded output after expansion, retain spacing between neighboring blocks, and restore the same presentation after session reload.
- Thinking-toggle tests must assert both state transitions, exact visible status text, refresh of existing blocks, refresh of a streaming block when present, and persistence across restart. They should test the public shortcut action rather than a private boolean.
- Styling tests should assert semantic style application and structural separation rather than terminal-specific escape sequences wherever possible. A small renderer-level assertion may verify that thinking, tool title, tool output, success, and error use distinct configured tokens.
- Filesystem tool tests should reuse the existing temporary-directory patterns and cover normal create/replace, parent creation, traversal and absolute-path rejection, excluded/generated/sensitive paths, symlink escape handling, empty files, Unicode text, and bounded output.
- Edit tests must cover exactly one match, zero matches, multiple matches, unchanged replacement, newline preservation, failed write behavior, and concise diff/result metadata.
- Bash tests should use a fake process or injected operation boundary for deterministic stdout/stderr, exit code, timeout, cancellation, truncation, and cwd assertions. One platform integration test may run a harmless command when the host shell is known; the core suite must not depend on Bash being installed on Windows.
- Tool-loop tests must prove normalized `write`, `edit`, and `bash` calls execute through the registry, persist structured results, and feed a continuation turn without the agent loop knowing tool-specific details.
- Resource-loader tests must cover user/project discovery, parent ordering, duplicate-name precedence, malformed metadata diagnostics, full skill-content retention, compact system-prompt skill metadata, context-file loading, system and append-system prompt precedence, trust/opt-out behavior, explicit paths, and reload behavior.
- Provider-boundary tests must assert the effective system prompt includes tools, context files, and visible skill metadata while excluding disabled skill bodies and provider-specific loader objects.
- Existing tests asserting automatic latest-session resume must be changed to assert explicit continuation. Existing `/new`, settings, focus, reasoning, and transcript restoration regressions must continue to pass.
- Full validation remains `uv run pytest`, `uv run mypy src/peon`, `git diff --check`, and workspace diagnostics. Focused tests for each slice must run before the full suite.
- Tests should assert user-visible behavior and normalized contracts, not private helper names, exact file enumeration order beyond the documented deterministic rule, or the internal shape of a renderer component.

## Out of Scope

- Full Pi command parity, including every session-tree, export, share, model, package, login, editor, and settings command.
- A web UI, fullscreen renderer, RPC protocol, or HTML exporter beyond the minimum structured print output needed for this spec.
- Automatic execution of every discovered skill. Discovery, model-visible metadata, explicit loading, and safe diagnostics are the target; a complete skill-command framework can be separate.
- Multi-agent orchestration, subagent definitions, background daemons, remote shells, containers, sandboxing, shell allowlists, and privilege escalation controls.
- A guarantee that arbitrary shell commands are safe. The spec defines cwd, exclusion, timeout, cancellation, and bounded-output behavior; stronger sandboxing requires a separate security design.
- Image-aware `read` behavior or binary file editing.
- Automatic code formatting, language-aware refactoring, patch conflict resolution, or multi-file transactional edits.
- Replacing the provider protocol, adding provider-specific tool branches to the agent loop, or moving filesystem policy into `agent`.
- Deleting or silently rewriting legacy sessions.
- A visual pixel-perfect clone of Pi's theme. Peon should match observable hierarchy, spacing, compactness, and status behavior using its own configurable presentation tokens.

## Further Notes

- Verified Pi behavior for this spec comes from the coding-agent session documentation, CLI argument parser, session manager, print mode, interactive mode, built-in tool renderers, resource loader, skills loader, system-prompt builder, and resource-loader tests in the Pi repository.
- The key startup decision is explicitness: `peon` starts new; `peon -c` continues recent; `peon -r` selects; `peon --session` opens an exact target. This intentionally changes Peon's current automatic-latest-session behavior.
- Pi's tool rendering is not simply "show or hide JSON." Its renderers provide compact action-specific call labels, bounded result previews, expansion hints, semantic colors, and deliberate spacing. Peon should adopt that contract without copying Pi's TypeScript component architecture.
- Pi progressively discloses skills: names and descriptions are model-visible, while the model reads the full skill file when relevant. This is the preferred context-budget behavior for Peon.
- Pi loads `AGENTS.md`/`CLAUDE.md` context files and system-prompt sources through a resource loader before building the effective system prompt. Peon currently discovers skill names only and has no equivalent loader.
- The proposed test seam has been synthesized from the existing public boundaries: session startup/store behavior, Textual application rendering, extension registry invocation, filesystem safety, and provider request construction. No new cross-layer seam is required before implementation.
- This document is specification-only. It does not implement the requested features.
- Local tracker publication is blocked because the checkout has no configured Git remote and no issue-creation integration is available in the current tool set. The document is ready to publish once the project owner supplies or configures the canonical tracker target; apply the `ready-for-agent` label at publication time.
