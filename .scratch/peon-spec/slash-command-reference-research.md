# Slash Command Reference Research

**Research date:** 2026-07-18

**Scope:** Slash-command definitions, command resolution, autocomplete, palette
presentation, keyboard behavior, and command-result UI in Pi, Tau, and OpenCode.

**Method:** Primary repository source and project documentation only. No Peon
runtime or test code was changed by this research. Pi and Tau were inspected at
fixed commits. OpenCode is an active repository, so source files are cited at
the file commits reported by GitHub and the user-facing command list is cited at
the documentation commit reported by GitHub.

## Executive Summary

- **Pi** has a small built-in command manifest, but dispatch remains explicit in
  the interactive mode. Its strongest reusable idea is a combined provider that
  treats slash commands, command arguments, and file references as one editor
  completion surface. Built-in commands, prompt templates, extension commands,
  and skill commands share the same completion provider.
- **Tau** has the clearest command behavior seam. `CommandRegistry` owns
  normalization, aliases, sorted listing, argument splitting, and typed
  `CommandResult` values. `search_terms` are deliberately distinct from
  executable aliases. Its Textual UI has a useful completion state with a
  selected index, wrapping navigation, grouped rows, wrapped descriptions, and
  a footer that changes its hints while completion is active.
- **OpenCode** models commands as a projection of a broader keymap registry.
  Palette entries carry a stable command name, title, description, category,
  visibility, enabled state, slash name, slash aliases, and keybindings. The
  TUI command menu uses fuzzy matching across display text, category,
  description, and keywords, groups the empty-query view by task area, and
  renders descriptions and keybindings beside the selected row.
- **Peon should combine these patterns, not copy any inventory literally.** Use
  Tau's registry/result boundary, Pi's source-aware completion composition, and
  OpenCode's distinction between slash commands and a broader command palette.
  Keep Peon's stronger product decision that descriptions and candidate terms
  are searchable, even though Pi's built-in command filter currently matches
  command names only.

## Source Snapshots

### Pi

- [Built-in slash command manifest](https://github.com/earendil-works/pi/blob/3da591ab74ab9ab407e72ed882600b2c851fae21/packages/coding-agent/src/core/slash-commands.ts)
- [Combined autocomplete provider](https://github.com/earendil-works/pi/blob/3da591ab74ab9ab407e72ed882600b2c851fae21/packages/tui/src/autocomplete.ts)
- [Interactive dispatch and selector UI](https://github.com/earendil-works/pi/blob/3da591ab74ab9ab407e72ed882600b2c851fae21/packages/coding-agent/src/modes/interactive/interactive-mode.ts)

### Tau

- [Command registry and built-ins](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/commands.py)
- [Completion state and matching](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/tui/autocomplete.py)
- [Textual app, prompt bindings, pickers, and command output](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/src/tau_coding/tui/app.py)
- [Registry tests](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/tests/test_commands.py)
- [Autocomplete and TUI behavior tests](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/tests/test_tui_autocomplete.py)
- [Textual interaction tests](https://github.com/huggingface/tau/blob/1b7db6fff00a006710111338ea421cff8115dfd2/tests/test_tui_app.py)

### OpenCode

- [User-facing TUI command list and descriptions](https://github.com/anomalyco/opencode/blob/8a2cfc00c93afc32a79979b7a928bc55d6483934/packages/web/src/content/docs/tui.mdx)
- [Keymap command-to-slash projection](https://github.com/anomalyco/opencode/blob/155e1f20d655eba12404772a4ddc90a52045cd7a/packages/tui/src/keymap.tsx)
- [Terminal slash autocomplete](https://github.com/anomalyco/opencode/blob/e8610d821c2b8262d077ff56c976be6c3d7e9c57/packages/tui/src/component/prompt/autocomplete.tsx)
- [Terminal command palette and fuzzy matching](https://github.com/anomalyco/opencode/blob/888c4cb50476aaecaad48e6a448759da3040ed2e/packages/opencode/src/cli/cmd/run/footer.command.tsx)
- [Terminal palette row rendering and grouping](https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/run/footer.menu.tsx)
- [Terminal prompt slash state machine](https://github.com/anomalyco/opencode/blob/fff0ec294c86d8866933b57b654c7f42f650ab80/packages/opencode/src/cli/cmd/run/footer.prompt.tsx)
- [Web slash popover](https://github.com/anomalyco/opencode/blob/3cd9ee5a735d709c51a92afd095c1d73dfed47bb/packages/app/src/components/prompt-input/slash-popover.tsx)

## Pi Findings

### Command inventory

`BUILTIN_SLASH_COMMANDS` defines these built-ins in source order:

`/settings`, `/model`, `/scoped-models`, `/export`, `/import`, `/share`,
`/copy`, `/name`, `/session`, `/changelog`, `/hotkeys`, `/fork`, `/clone`,
`/tree`, `/trust`, `/login`, `/logout`, `/new`, `/compact`, `/resume`,
`/reload`, and `/quit`.

Each built-in carries a canonical `name`, a description, and optionally an
`argumentHint`. The manifest does not carry aliases or handlers. Interactive
dispatch checks built-in strings explicitly, while extension commands are
resolved through the extension runner.

Pi's current built-in descriptions include useful action wording such as
"Select model (opens selector UI)", "Create a new fork from a previous user
message", "Navigate session tree (switch branches)", and "Reload keybindings,
extensions, skills, prompts, themes, and context files".

### Completion and matching

`CombinedAutocompleteProvider` combines:

- Built-in slash commands.
- Prompt templates exposed as slash commands.
- Extension commands, excluding names that conflict with built-ins.
- Optional `skill:<name>` commands.
- Model argument completion for `/model`.
- Provider argument completion for `/login`.
- File and directory completion, including `@` references.

When the editor starts with `/` and has no space, Pi fuzzy-filters command
names. The result row displays the command name plus its argument hint and
description. Once the command name is followed by a space, only that command's
argument completion provider is consulted. Built-in command filtering therefore
does not search descriptions or general keywords; this is a useful contrast
with Tau and OpenCode.

Selecting a slash command inserts the canonical name and a trailing space,
leaving the editor ready for arguments. File completion preserves directory
continuation, quoted paths, and `@` prefixes. File search uses `fd`, respects
ignored directories, scores exact and prefix filename matches above broader
matches, and limits the displayed fuzzy results.

### Dispatch and UI

The interactive mode clears the editor before opening selectors or running
commands. Built-ins open selector components in place of the editor for model,
settings, login, sessions, trees, and related flows. Command output is rendered
as status text, transcript content, or a focused selector depending on the
command. Extension UI can provide selectors, inputs, editors, overlays, header
and footer replacements, widgets, and autocomplete providers.

The command editor is part of the normal prompt rather than a separate
full-screen command screen. Startup hints explicitly advertise `/` for
commands, `!` and `!!` for shell execution, and Tab for path completion or
autocomplete acceptance. Escape cancels autocomplete or aborts the active
operation according to current state.

## Tau Findings

### Command registry and inventory

Tau's `SlashCommand` metadata contains `name`, `description`, `usage`,
`handler`, `aliases`, and `search_terms`. `CommandRegistry` owns registration,
duplicate detection, alias resolution, sorted listing, command parsing, and
execution. It normalizes the leading slash, surrounding whitespace, and case.
Arguments are split only after the first command token is identified.

The default registry lists these canonical commands, sorted by name:

`/compact`, `/export`, `/hotkeys`, `/login`, `/logout`, `/model`, `/name`,
`/new`, `/quit`, `/reload`, `/resume`, `/scoped-models`, `/session`, `/skill`,
`/system`, `/theme`, and `/tree`.

Verified executable aliases and special resolution:

- `/exit` is an executable alias for `/quit`.
- `/scoped models` resolves to `/scoped-models`.
- `/clear` and `/reset` are search terms for `/new`, not executable aliases.
- `/info` is a search term for `/session`, not a separate command.
- `/history`, `/previous`, `/branch`, `/fork`, `/rename`, `/title`, and similar
  terms are search vocabulary where registered, not duplicate handlers.
- `/skill:<name>` is intentionally left unhandled by the registry so skill
  expansion can occur in the prompt path.

This distinction between executable aliases and search vocabulary is directly
useful for Peon's candidate-name and hidden-compatibility design.

### Completion and matching

Tau's `CompletionState` owns the visible items and selected index. Selection
wraps at both ends. Completion generation handles, in order:

1. File references beginning with `@`.
2. Shell path completion after `!` or `!!`.
3. Skill-name completion after `/skill:`.
4. Typed command argument completion for models, providers, sessions, and
   themes.
5. Canonical commands, aliases, and search terms.
6. Custom prompt templates in a separate `Custom prompts` category.

Canonical command prefixes rank ahead of search-term matches. An alias or
search-term match inserts the canonical command, not the vocabulary that
caused the match. For example, searching `/cl` suggests `/new` and accepting
it inserts `/new`.

After a canonical command or prompt template is complete and followed by a
space, command-name completion hides and argument completion takes over. The
tests also establish an important interaction rule: Enter accepts the selected
completion first and does not submit the command in that same keypress. A
second Enter submits the completed command.

### UI and interaction

Tau exposes a command palette keybinding, Ctrl+K by default, by placing `/` in
the prompt and refreshing completion. The prompt remains the main focus; the
completion list appears above it. In completion mode the Textual footer changes
to show Choose with Up/Down, Complete with Tab/Enter, and Close with Escape.

The completion renderer groups commands and custom prompts, aligns descriptions
under a stable column, wraps long descriptions, and computes a bounded visible
window that always keeps the selected row visible. The window size is kept
stable during a completion session so changing the selected row cannot cause
progressive layout shrinkage.

Command result UI is deliberately typed:

- `/session`, `/hotkeys`, and similar long output use a centered, scrollable
  command-output modal.
- `/reload` and `/system` append output to the transcript.
- `/name` uses a notification for its success result.
- `/login`, `/model`, `/theme`, `/resume`, and `/tree` open focused modal
  pickers with explicit Escape cancellation and Up/Down/Enter handling.
- Picker and completion controls use the same keyboard vocabulary while the
  footer communicates the active mode.

## OpenCode Findings

### User-facing slash inventory

The TUI documentation lists these built-in slash commands:

| Command | Verified aliases or behavior |
| --- | --- |
| `/connect` | Add a provider and API key. |
| `/compact` | Alias `/summarize`. |
| `/details` | Toggle tool execution details. |
| `/editor` | Open the external editor. |
| `/exit` | Aliases `/quit` and `/q`. |
| `/export` | Export the conversation to Markdown and open it in the editor. |
| `/help` | Show the help dialog. |
| `/init` | Guided `AGENTS.md` setup. |
| `/models` | List available models. |
| `/new` | Alias `/clear`; start a new session. |
| `/redo` | Redo a previously undone message and file changes. |
| `/sessions` | Aliases `/resume` and `/continue`; list and switch sessions. |
| `/share` | Share the current session. |
| `/themes` | List available themes. |
| `/thinking` | Toggle visibility of thinking blocks, distinct from reasoning capability. |
| `/undo` | Undo the last message and associated file changes. |
| `/unshare` | Remove sharing from the current session. |

The OpenCode docs explicitly distinguish `/thinking` display visibility from
actual reasoning capability, which is changed through a separate model-variant
control. That separation is a useful warning against making one Peon command
silently combine presentation and model-policy state.

### Registry and command palette

OpenCode's current TUI keymap exposes command entries with a stable internal
command name, title, description, category, namespace, visibility/enabled
state, optional keybinding, slash name, and slash aliases. The slash projection
filters to reachable, non-hidden palette commands and dispatches the internal
command name. This makes slash invocation one view of a larger command/keymap
registry rather than the sole command authority.

The terminal command palette adds commands that are not necessarily slash
commands, including model switching, editor access, skills, queued messages,
subagents, and variant controls. It groups the empty-query list into Session,
Prompt, Agent, project/MCP commands, and System categories. Project and MCP
commands are loaded dynamically and are sorted within their category.

### Matching and keyboard behavior

OpenCode's terminal palette fuzzy-matches `display`, `category`, `description`,
and `keywords`. The prompt autocomplete path additionally matches aliases and
gives a direct prefix match a score boost. Results are capped to a small visible
set, and the selected index resets when the query changes.

The terminal command palette supports Escape or Ctrl+C to close, Up/Down and
Ctrl+P/Ctrl+N to move, PageUp/PageDown, Home/End, and Enter to select. Its menu
state clamps movement at the first and last row rather than wrapping. The
inline prompt autocomplete uses a separate state that wraps Up/Down selection.
This is an important distinction: OpenCode has more than one menu interaction
model, chosen by the surface.

Rows show a selected marker, selected foreground/background, a display label,
truncated description, and an optional footer value for slash text, current
state, or keybinding. Empty-query terminal palette rows are grouped with
headers; filtered results become a direct list. The web slash popover similarly
shows `/trigger`, description, source badges for custom/MCP/skill commands, and
the command keybinding, with a highlighted active row and pointer selection.

### Prompt semantics

OpenCode's prompt state machine opens slash autocomplete when the cursor is at
the slash command head, hides it after the command has arguments, and parses a
command only when the head matches a known command. Selecting a command replaces
the slash head with the canonical slash name and a separator. This preserves
the draft and leaves the editor focused. A completed command then follows the
normal submit path.

## Reconciliation for Peon

### Adopt

1. Keep one shared catalog with a stable command ID and separate canonical name,
   executable aliases, search terms, description, availability, and argument
   policy.
2. Use a typed invocation/result boundary like Tau's `CommandResult`; renderer
   behavior such as transcript output, notification, modal, or selector remains
   outside the catalog.
3. Build completion candidates from the catalog plus future extension or skill
   sources, with source metadata available for diagnostics and optional hints.
4. Keep canonical replacement when a candidate, alias, or description term
   matched. Do not insert `/reset`, `/summarize`, or another search term when the
   canonical command is `/new` or `/compact`.
5. Use a selected completion state with wraparound Up/Down, selected-row
   styling, a bounded window, wrapped descriptions, and active footer hints.
6. Treat a command menu and inline slash completion as related but separate
   surfaces. A future broad palette may contain non-slash actions; slash
   completion should remain lightweight and prompt-local.
7. Keep source-specific command behavior out of the catalog. For example,
   `/thinking` must not imply whether it controls reasoning tokens, visibility,
   or model variants until Peon defines that contract.

### Do not adopt literally

- Pi's manual string dispatch and lack of general description matching.
- Tau's search-term behavior as executable aliases.
- OpenCode's broad command/keymap namespace as Peon's initial command surface.
- OpenCode's clamped terminal palette navigation if Peon's single inline
  completion surface promises wraparound navigation.
- Any upstream command merely because it exists. Peon's existing product
  decision still controls whether a command is available, reserved, or hidden.

### Recommended inventory changes

- Keep `/provider` as Peon's canonical provider onboarding command, with
  `/login` and `/connect` as candidate vocabulary informed by Tau/Pi and
  OpenCode respectively.
- Keep `/model` as Peon's canonical model command. Treat `/models` as a
  compatibility candidate or alias, not a second purpose.
- Keep `/new` as canonical. `/clear` is a verified OpenCode alias and Tau's
  `/clear`/`/reset` are verified search terms; Peon may support both as hidden
  compatibility aliases if migration requires executable compatibility.
- Keep `/quit` as canonical. `/exit` and `/q` are verified upstream vocabulary;
  `/close` remains a Peon compatibility choice rather than an upstream parity
  claim.
- Promote `/session`, `/compact`, `/export`, `/share`, `/thinking`, `/theme`,
  `/editor`, `/undo`, `/redo`, `/tree`, `/reload`, and `/init` from speculative
  reference notes to researched future contracts, but do not mark them
  implemented.
- Keep `/copy`, `/usage`, `/extensions`, and `/skills` as product decisions,
  not universal parity claims. Their upstream support is partial or
  source-specific: Pi has `/copy`, OpenCode has dynamic skill/palette entries,
  and Tau exposes related data through other commands.

## Research Gate Result

Issue 20 is complete as a research task. Implementation issues 16-19 remain
separate; this document does not authorize code changes or claim that Peon has
implemented any newly documented command.