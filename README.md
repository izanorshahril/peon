# Peon

Peon is a minimal modular Python coding agent with a Pi-like terminal
experience and Tau-style architecture. It keeps provider transport, portable
agent runtime, application policy, and executable extensions separate.

```text
src/peon/
  agent/       messages, loop, events, execution contracts
  ai/          provider adapters
  app/         CLI, TUI, configuration, sessions, resources
  extensions/  tools, skills, hooks, registration
```

## Development

Requires Python 3.13 and `uv`.

```powershell
uv sync
uv run pytest
uv run mypy src/peon
```

## Run

Start Textual interactive mode:

```powershell
uv run peon
```

Run one task against an OpenAI-compatible endpoint:

```powershell
uv run peon "Summarize this repository" `
  --provider openai-compatible `
  --base-url "http://localhost:11434/v1" `
  --model "local-model"
```

Use `--api-key` for authenticated endpoints. Provider profiles and UI settings
persist locally; set `PEON_CONFIG_FILE` to override profile path.

Print only final output, optionally reading piped stdin:

```powershell
Get-Content README.md | uv run peon -p "Summarize this input"
```

Add `--events` (`--jsonl` or `--json`) for one JSON event per line.
`fullscreen` and `webapp` interaction levels are reserved, not implemented.

## Sessions

Interactive runs create append-only JSONL sessions under `~/.peon/sessions`.
Set `PEON_SESSION_DIR` to override location.

```text
--continue, -c       resume newest session for current directory
--session TARGET     resume by ID, unique name, or JSONL path
--session-name NAME  name a new session
--no-session         use ephemeral conversation
```

Print mode is ephemeral unless durable session flags are explicit. `/new`
starts a fresh session, `/session` shows the active session details, `/resume`
opens current-project history, and `/fork [name]` creates a child with parent
metadata. Session history rows show the first prompt, interaction count, and
relative age. Set the `session-list-delimiter` general setting to `false` for
single-space Pi-style rows instead of dot delimiters.

## Tools and Resources

Registry provides cwd-bound `read`, `write`, `edit`, `bash`, `ls`, `find`, and
`grep`; first four are enabled by default. Tool availability is configurable.
Filesystem mutations reject paths outside cwd, sensitive targets, symlink
targets, and ambiguous edits; bash supports timeout, bounded output, and
cancellation.

Peon discovers project/user skills, `AGENTS.md` or `CLAUDE.md`, `SYSTEM.md`,
and `APPEND_SYSTEM.md`. CLI flags can supply explicit resources or disable
discovery. Effective prompt assembly stays in application layer; generated
resource prompts are not persisted as conversation messages.

## Interactive Commands

Type `/help` for current available and reserved commands. Main workflows cover
new/resumed/forked sessions, model/provider switching, settings, reasoning,
tools, skills, and logout. Provider-field commands remain hidden compatibility
aliases managed through `/settings`. Use the `system-text-format` UI setting to
choose normal, bold, or italic startup/system text. Textual shortcuts default to `Ctrl+T` for
thinking visibility, `Shift+Tab` for reasoning, and `Ctrl+O` for tool output.

## Scope

Peon core does not own report generation, workbook schemas, image evidence,
dashboards, RAG, fine-tuning, or autonomous self-improvement. External
applications can expose those capabilities through extension contracts.

See [.scratch/project-history.md](.scratch/project-history.md) for architecture
decisions, completed history, remaining Pi gaps, and primary research sources.
