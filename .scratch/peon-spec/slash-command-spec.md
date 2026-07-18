# Peon Slash Command System

## Problem Statement

Peon's slash commands grew incrementally across two terminal shells. Command names, descriptions, matching, completion, and dispatch are duplicated. Useful actions sit beside low-value provider-field commands such as `/provider-name`, making command discovery noisy. Textual shows matches but always treats the first match as selected; users cannot move through suggestions with Up/Down. Matching only considers command-name prefixes, so users must already know exact vocabulary.

Peon also lacks a deliberate future command surface. Pi, Tau, and OpenCode are
now verified references; their exact inventories, command-resolution seams, and
palette behavior are recorded in
[Slash Command Reference Research](slash-command-reference-research.md).
The research confirms that command names, aliases, search vocabulary, and UI
actions are separate concerns in the strongest implementations. Without a
living inventory, future work risks adding duplicate names, implementing
already-completed behavior twice, or exposing placeholders as if they worked.

## Solution

Build one shared slash-command system consumed by both terminal shells. It will own canonical names, candidate names, aliases, short descriptions, search terms, availability, ordering, argument policy, and resolution. Renderers will own presentation and keyboard input only.

Typing `/` opens a Pi-style command list. Each row shows canonical command plus
short description without numeric bullets; the selected row uses an arrow and
the same highlight treatment as a picker. Candidate names appear as compact
hint text and participate in matching. Search considers canonical name,
candidate names, and description terms, with deterministic ranking. The palette
shows the selected position and total result count plus a footer with keyboard
hints. Up/Down changes selected match, Tab completes it, Enter accepts an
incomplete selected completion before command execution, and Escape dismisses
suggestions. This follows Tau's tested completion-first behavior while keeping
the composer focused.

Keep top-level command surface task-oriented. Provider-field commands move into `/settings`; compatibility aliases may continue resolving without appearing as primary commands. Add useful implemented commands under canonical names. Add future commands as explicit reserved entries with honest unavailable feedback. Maintain living command inventory recording implementation status, candidate names, source-reference status, and owning issue.

Initial command inventory uses current Peon behavior plus locally known product
needs. Verified upstream vocabulary informs candidates and reserved contracts,
but exact parity is not a goal and no upstream command is considered
implemented in Peon merely because it appears in the inventory.

## User Stories

1. As an operator, I want typing `/` to show available commands, so that I can discover actions without reading documentation.
2. As an operator, I want every command row to show a short description, so that I understand its effect before running it.
3. As an operator, I want candidate names shown beside a command, so that alternate vocabulary teaches me the canonical name.
4. As an operator, I want command search to match canonical names, so that known commands remain fast to find.
5. As an operator, I want command search to match candidate names, so that `/reset` can find canonical `/new`.
6. As an operator, I want command search to match description words, so that `/switch model` can find `/model`.
7. As an operator, I want search to ignore case, punctuation separators, and repeated whitespace, so that minor formatting differences do not hide commands.
8. As an operator, I want exact canonical matches ranked first, so that search remains predictable.
9. As an operator, I want prefix matches ranked ahead of loose description matches, so that direct intent wins.
10. As an operator, I want stable ordering for equal matches, so that suggestions do not jump while I type.
11. As an operator, I want Up/Down to move through visible commands, so that I can select alternatives without editing text.
12. As an operator, I want selection to wrap at list boundaries, so that repeated navigation stays quick.
13. As an operator, I want selected command visually distinct, so that Enter behavior is obvious.
14. As an operator, I want Tab to complete selected canonical command, so that I can add arguments before execution.
15. As an operator, I want Enter to execute selected command, so that keyboard command use needs no mouse.
16. As an operator, I want Escape to close suggestions without losing draft input, so that discovery is reversible.
17. As an operator, I want unknown slash input to produce concise guidance, so that typos do not become chat messages.
18. As an operator, I want `/new` to start a clean conversation, so that session reset uses action-oriented vocabulary.
19. As an existing operator, I want `/clear` and `/reset` to find or alias `/new`, so that vocabulary changes do not break habits.
20. As an operator, I want `/model` to list and switch saved provider/model choices, so that separate `/models` command is unnecessary.
21. As an existing operator, I want `/models` to find or alias `/model`, so that current usage remains compatible.
22. As an operator, I want `/provider` to add or connect provider profiles, so that provider onboarding remains direct.
23. As an operator, I want `/settings` to edit UI and saved-provider configuration, so that low-level config does not pollute command list.
24. As an operator, I want `/tools` to inspect available tools, so that model capabilities remain visible.
25. As an operator, I want `/help` to explain commands and key behavior, so that command discovery has a durable entry point.
26. As an operator, I want `/logout` to remove saved provider credentials, so that account cleanup remains explicit.
27. As an operator, I want `/quit` to exit Peon, so that terminal lifecycle remains clear.
28. As an existing operator, I want `/exit`, `/close`, and `/q` to find `/quit`, so that common exit vocabulary works.
29. As an operator, I want provider tuning fields absent from primary command list, so that useful actions are not buried.
30. As an existing operator, I want retired field commands to resolve as hidden compatibility aliases during migration, so that scripts do not fail abruptly.
31. As an operator, I want reserved commands visible with a Reserved hint, so that future direction is discoverable without pretending features exist.
32. As an operator, I want running a reserved command to explain that it is unavailable, so that no placeholder silently does nothing.
33. As an operator, I want `/session` reserved for list/resume/history behavior, so that session vocabulary has one future canonical home.
34. As an operator, I want `/compact` reserved for context compaction, so that context management has a clear future command.
35. As an operator, I want `/export` reserved for conversation export, so that saving sessions has a clear future command.
36. As an operator, I want `/share` reserved for publish/share behavior, so that remote sharing remains distinct from local export.
37. As an operator, I want `/copy` reserved for copying latest response, so that common transcript action is keyboard accessible later.
38. As an operator, I want `/status` reserved for provider/model/context state, so that diagnostics have one command.
39. As an operator, I want `/usage` reserved for token and cost usage, so that accounting can be added without renaming.
40. As an operator, I want `/thinking` reserved for reasoning controls, so that reasoning vocabulary is task-oriented rather than provider-field-oriented.
41. As an operator, I want `/theme` reserved for visual theme selection, so that UI customization has a direct future entry point.
42. As an operator, I want `/editor` reserved for external-editor composition, so that long prompts can use editor workflow later.
43. As an operator, I want `/undo` and `/redo` reserved for conversation edits, so that reversible transcript changes have stable names.
44. As an operator, I want `/fork` and `/tree` reserved for session branching, so that future branch navigation is coherent.
45. As an operator, I want `/skills` and `/extensions` available for capability inspection and management, so that extensibility remains visible.
46. As an operator, I want `/reload` reserved for refreshing dynamic capabilities, so that extension reload has one future action.
47. As an operator, I want `/init` reserved for project instruction setup, so that coding-agent onboarding has a stable future name.
48. As a maintainer, I want one command catalog shared by all shells, so that names and matching cannot drift.
49. As a maintainer, I want command behavior represented by stable command IDs rather than display strings, so that aliases do not duplicate handlers.
50. As a maintainer, I want availability explicit as available, reserved, or hidden compatibility, so that UI and execution agree.
51. As a maintainer, I want command arguments separated from search text only after exact command resolution, so that description search can include spaces.
52. As a maintainer, I want one living inventory linked to issues, so that completed and future commands stay organized.
53. As a maintainer, I want completed issues kept as history and excluded from active backlog, so that agents do not repeat finished work.
54. As a maintainer, I want source-project claims marked unverified until inspected, so that memory is not mistaken for research.
55. As a maintainer, I want future upstream reconciliation isolated from implementation, so that current cleanup can proceed offline.
56. As a user of either terminal shell, I want equivalent command search and resolution, so that switching renderers does not change command language.

## Implementation Decisions

- Introduce one application-level `CommandCatalog` as primary behavior seam. Both prompt-toolkit and Textual consume same catalog.
- Define each command with stable ID, canonical name, candidate names, concise description, search terms, availability, argument policy, and display order.
- Availability states are `available`, `reserved`, and `hidden-compatibility`. Reserved commands appear with honest status. Hidden compatibility aliases resolve but do not clutter default list.
- Candidate names are search vocabulary, not separate handlers. One purpose gets one canonical name.
- Search normalization removes leading slash, folds case, treats hyphens/underscores as spaces, collapses whitespace, and tokenizes descriptions.
- Ranking order is exact canonical, canonical prefix, exact candidate, candidate prefix, all-token match, description/search-term match, then catalog order.
- If first token exactly resolves to canonical name or compatibility alias, remaining text is arguments. Otherwise all text after slash remains search query.
- Textual command palette keeps selected index as query changes when selected command remains visible; otherwise selects first result.
- Up/Down cycle visible matches with wraparound. Tab inserts selected canonical name and keeps composer active. Enter accepts a selected incomplete completion first; a later Enter invokes the completed command. Escape hides palette and preserves composer text.
- Prompt-toolkit uses same search results and descriptions through its completer. Native Up/Down completion navigation remains, but ordering and metadata come from shared catalog.
- Keep inline slash completion prompt-local. A later broader command palette may contain non-slash actions, following OpenCode's keymap projection, but it must still dispatch stable command IDs.
- Initial primary available commands are `/help`, `/new`, `/model`, `/provider`, `/settings`, `/tools`, `/skills`, `/logout`, and `/quit`.
- `/clear` and `/reset` become compatibility vocabulary for `/new`. `/models` becomes compatibility vocabulary for `/model`. `/exit`, `/close`, and `/q` become compatibility vocabulary for `/quit`.
- Provider-field commands leave primary surface: `/temperature`, `/reasoning`, token-limit commands, support toggles, `/base-url`, `/api-key`, `/response-format`, and `/provider-name`. Their settings remain available through `/settings`; temporary hidden aliases preserve migration compatibility.
- Initial reserved commands are `/session`, `/compact`, `/export`, `/share`, `/copy`, `/status`, `/usage`, `/thinking`, `/theme`, `/editor`, `/undo`, `/redo`, `/fork`, `/tree`, `/extensions`, `/reload`, and `/init`.
- Reserved inventory records researched future contracts, not proof of implementation or exact Pi/Tau/OpenCode parity. The source evidence and the product decision remain separate.
- Registered extension skills appear as dynamic `/skill:<name>` completion entries. `/skills` lists their names; loading and execution remain owned by the extension registry rather than the application shell.
- Picker rows use the same arrow/highlight presentation as slash commands. Pickers provide search, current/total counts, and keyboard hints, and app-owned navigation remains active after focus moves away from the search field.
- Selected command foreground color is configurable through UI settings and defaults to black on the existing grey highlight.
- Command execution uses stable IDs and typed invocation results. Shell-specific presentation effects remain renderer-owned; shared service owns resolution and availability checks.
- Existing agent loop, provider adapters, context model, settings hierarchy, and provider persistence remain unchanged unless command naming requires routing updates.
- Completed issue history remains in place. Active map will separate completed foundation from new command-system backlog.

## Testing Decisions

- Highest test seam is public `CommandCatalog` behavior. Search, ranking, aliases, description matching, availability, and argument parsing are tested without either renderer.
- Good tests assert operator-visible behavior and stable command IDs, not private list storage or exact helper functions.
- Catalog tests cover canonical exact/prefix matching, candidate matching, description-token matching, normalization, stable ties, hidden aliases, reserved status, and no-match behavior.
- Catalog tests prove one purpose maps to one handler ID even when several candidate names match.
- Textual harness tests only renderer behavior not covered by catalog: list visibility, short descriptions, candidate hints, selected-row style, Up/Down movement, Tab completion, Enter invocation, Escape dismissal, and selection retention after query changes.
- Prompt-toolkit tests verify completer consumes catalog order/metadata and exposes descriptions; avoid testing prompt-toolkit internals.
- Command-boundary tests verify available commands dispatch, reserved commands return concise unavailable feedback, compatibility aliases dispatch same command ID, and unknown commands never enter agent conversation.
- Existing TUI command tests provide prior art for command completion, abbreviated resolution, model switching, settings navigation, and session clearing.
- Existing agent/provider tests remain unchanged because command cleanup must not alter model or tool behavior.
- Full regression requires both TUI suites, complete pytest suite, mypy, and diff hygiene.

## Out of Scope

- Claiming exact source-project command parity before verification.
- Implementing behavior behind every reserved command.
- Persistent chat sessions, context compaction, export/share services, token accounting, external editor integration, undo/redo, session trees, skill loading, extension reload, or project initialization.
- Reworking provider request schemas, settings persistence, model switching, transcript rendering, or agent loop.
- New web or fullscreen renderer.
- Mouse-first command palette behavior.

## Further Notes

- Primary reference order remains Pi first, then Tau and OpenCode for useful additions absent from Pi. Verified evidence is maintained in [Slash Command Reference Research](slash-command-reference-research.md).
- `reference.txt` is source index only; it does not contain command inventories.
- Issue 20 records the completed research gate. Implementation remains in issues 16-19 and must not be inferred from the research report.
- Proposed test seam matches current code evidence: names, descriptions, matching, and resolution are duplicated between prompt-toolkit and Textual, while keyboard rendering exists only in Textual.
- Local issue drafts 01–15 describe completed foundation and remain historical. New command work starts at issue 16.
- Tracker publication is pending because local `gh` is authenticated to `github.st.com`, while origin points to `github.com/izanorshahril/peon`. Publish active implementation issues with `ready-for-agent` once matching tracker authentication exists.
