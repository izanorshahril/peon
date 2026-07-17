"""Textual renderer for Peon's minimal interactive mode."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.document._document import Selection
from textual.events import Key, MouseDown
from textual.strip import Strip
from textual.worker import Worker, WorkerState
from textual.widgets import Input, Label, ListItem, ListView, Static, TextArea
from textual.containers import VerticalScroll

from peon.agent import AgentContext, ModelProvider, ToolCall, run_task
from peon.ai import ProviderError
from peon.extensions import ExtensionRegistry

from .cli import CommandError, ProviderConfig, ProviderFactory, create_provider
from .config import ProviderConfigStore, provider_id

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_MARKDOWN_CONSOLE = Console(width=4096)


def _render_markdown_lines(markdown: str) -> list[Text]:
    """Convert Markdown into compact, styled, selectable transcript lines."""
    lines = _MARKDOWN_CONSOLE.render_lines(
        Markdown(markdown),
        options=_MARKDOWN_CONSOLE.options.update_width(4096),
        pad=False,
    )
    rendered_lines: list[Text] = []
    for segments in lines:
        line = Text(end="")
        for segment in segments:
            line.append(segment.text, style=segment.style)
        plain = line.plain
        leading = len(plain) - len(plain.lstrip())
        trailing = len(plain) - len(plain.rstrip())
        end = max(leading, len(plain) - trailing)
        rendered_line = line[leading:end] if end > leading else Text()
        rendered_line.end = ""
        rendered_lines.append(rendered_line)
    return rendered_lines or [Text(end="")]
_PROVIDER_OPTIONS = (
    ("openai-compatible", "OpenAI-compatible"),
    ("github-copilot", "GitHub Copilot"),
)
_COMMAND_SPECS = (
    ("/help", "show available commands"),
    ("/model", "switch the active model"),
    ("/models", "list detected models"),
    ("/provider", "configure a provider"),
    ("/logout", "remove one saved provider"),
    ("/tools", "list registered tools"),
    ("/clear", "clear conversation context"),
    ("/quit", "exit Peon"),
)


def _matching_commands(prefix: str) -> list[str]:
    name, _, _argument = prefix.partition(" ")
    lowered_name = name.lower()
    return [
        command
        for command, _description in _COMMAND_SPECS
        if command.startswith(lowered_name)
    ]


def _resolve_command(command: str) -> str:
    name, separator, argument = command.partition(" ")
    matches = _matching_commands(command)
    if not matches:
        return command
    resolved = next((match for match in matches if match == name.lower()), matches[0])
    return f"{resolved}{separator}{argument}" if separator else resolved


SetupStep = Literal[
    "provider",
    "saved-provider",
    "logout-provider",
    "base-url",
    "api-key",
    "copilot-token",
    "model",
]


class PeonInput(Input):
    """Composer input with live slash-command hints and Escape clearing."""

    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            cast(TextualPeonApp, self.app).action_confirm_quit()
        elif event.key == "tab":
            command = _resolve_command(self.value)
            if command != self.value:
                self.value = command
                self.cursor_position = len(command)
                event.stop()
                event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        suggestions = self.app.query_one("#suggestions", Static)
        if event.value.startswith("/") and " " not in event.value:
            prefix = event.value.lower()
            matches = [
                (command, description)
                for command, description in _COMMAND_SPECS
                if command.startswith(prefix)
            ]
            rendered = Text()
            for index, (command, description) in enumerate(matches):
                if index:
                    rendered.append("\n")
                rendered.append("> " if index == 0 else "  ", style="dim")
                rendered.append(command, style="bold reverse" if index == 0 else "")
                rendered.append(f"  {description}", style="dim")
            suggestions.update(rendered)
        else:
            suggestions.update("")

    def action_clear(self) -> None:
        self.value = ""
        self.app.query_one("#suggestions", Static).update("")

    def action_confirm_quit(self) -> None:
        cast(TextualPeonApp, self.app).action_confirm_quit()


class ChatMessage(TextArea):
    """Single selectable transcript surface with role-aware line styling."""

    USER_BACKGROUND = "#3a3a44"
    USER_FOREGROUND = "#c4c4c4"
    THINKING_FOREGROUND = "#808080"
    SUCCESS_FOREGROUND = "#8bd5ff"

    def __init__(
        self,
        text: str = "",
        *,
        role: str = "system",
        id: str | None = None,
        user_top_blank_lines: int = 1,
        user_bottom_blank_lines: int = 1,
        message_left_padding: int = 1,
    ) -> None:
        super().__init__(
            "",
            read_only=True,
            show_line_numbers=False,
            soft_wrap=True,
            id=id,
        )
        self._line_roles: list[str] = []
        self._styled_lines: list[Text] = []
        self._snapping_selection = False
        self.user_top_blank_lines = max(0, user_top_blank_lines)
        self.user_bottom_blank_lines = max(0, user_bottom_blank_lines)
        self.message_left_padding = max(0, message_left_padding)
        self.display = False
        if text:
            self.append_message(text, role=role)

    def append_message(self, text: str, *, role: str) -> None:
        styled_lines = (
            [Text(line, end="") for line in text.split("\n") or [""]]
            if role == "user"
            else _render_markdown_lines(text)
        )
        if role == "user":
            styled_lines = (
                [Text("", end="")] * self.user_top_blank_lines
                + styled_lines
                + [Text("", end="")] * self.user_bottom_blank_lines
            )
        elif role == "assistant":
            styled_lines = (
                [Text("", end="")] * self.user_top_blank_lines
                + styled_lines
                + [Text("", end="")] * self.user_bottom_blank_lines
            )
        self._styled_lines.extend(styled_lines)
        self._line_roles.extend([role] * len(styled_lines))
        self.text = "\n".join(line.plain for line in self._styled_lines)
        self.display = True
        self.scroll_end(animate=False)

    def clear_transcript(self) -> None:
        self.text = ""
        self._line_roles = []
        self._styled_lines = []
        self.selection = Selection.cursor((0, 0))
        self.display = False

    def get_line(self, line_index: int) -> Text:
        if line_index < len(self._styled_lines):
            line = self._styled_lines[line_index].copy()
        else:
            line = super().get_line(line_index)
        role = self._line_roles[line_index] if line_index < len(self._line_roles) else "system"
        if role == "user":
            line.stylize(
                Style(color=self.USER_FOREGROUND, bgcolor=self.USER_BACKGROUND)
            )
        elif role in {"system", "thinking"}:
            line.stylize(Style(color=self.THINKING_FOREGROUND, italic=True))
        elif role == "success":
            line.stylize(Style(color=self.SUCCESS_FOREGROUND))
        return line

    def render_line(self, y: int) -> Strip:
        strip = super().render_line(y)
        if not self.text:
            return Strip.blank(
                strip.cell_length,
                Style(bgcolor=self.styles.background.rich_color),
            )
        y_offset = y + self.scroll_offset.y
        if y_offset >= self.wrapped_document.height:
            return strip
        line_info = self.wrapped_document._offset_to_line_info[y_offset]
        if line_info is None:
            return strip
        line_index, _section_offset = line_info
        role = self._line_roles[line_index] if line_index < len(self._line_roles) else "system"
        role_style: Style | None = None
        if role == "user":
            role_style = Style(bgcolor=self.USER_BACKGROUND)
        elif role == "assistant":
            role_style = Style(bgcolor=self.styles.background.rich_color)
        elif role == "success":
            role_style = Style(color=self.SUCCESS_FOREGROUND)
        if role_style is not None:
            strip = Strip(
                Segment.apply_style(strip, post_style=role_style),
                cell_length=strip.cell_length,
            )
        if role in {"user", "assistant"} and self.message_left_padding:
            padding = min(self.message_left_padding, strip.cell_length)
            first_style = next(
                (segment.style for segment in strip if segment.cell_length),
                None,
            )
            strip = Strip.join(
                [
                    Strip([Segment(" " * padding, first_style)], padding),
                    strip.crop(0, strip.cell_length - padding),
                ]
            )
        return strip

    def _snap_selection_to_lines(self, selection: Selection) -> Selection:
        start, end = selection
        if start == end:
            return selection
        first, last = sorted((start, end))
        snapped_start = (first[0], 0)
        snapped_end = (last[0], len(self.document[last[0]]))
        if start <= end:
            return Selection(snapped_start, snapped_end)
        return Selection(snapped_end, snapped_start)

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        if self._snapping_selection or event.selection.is_empty:
            return
        snapped = self._snap_selection_to_lines(event.selection)
        if snapped == self.selection:
            return
        self._snapping_selection = True
        try:
            self.selection = snapped
        finally:
            self._snapping_selection = False

    async def _on_mouse_down(self, event: MouseDown) -> None:
        if event.button != 3:
            await super()._on_mouse_down(event)
            return
        text = self.selected_text
        if text:
            cast(TextualPeonApp, self.app).copy_to_clipboard(text)
        event.stop()
        event.prevent_default()


class ProcessingStatus(Static):
    """Configurable animated processing indicator."""

    FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")

    def __init__(self, text: str, *, id: str) -> None:
        super().__init__(id=id)
        self.text = text
        self.frame = 0

    def on_mount(self) -> None:
        self.set_interval(0.12, self._advance)
        self._render_status()

    def _advance(self) -> None:
        self.frame = (self.frame + 1) % len(self.FRAMES)
        self._render_status()

    def _render_status(self) -> None:
        self.update(
            Text.assemble(
                (self.FRAMES[self.frame], "#8bd5ff"),
                (f" {self.text}", "#808080"),
            )
        )


class TextualPeonApp(App[int]):
    """Stable terminal UI with a scrollable transcript and fixed composer."""

    PROCESSING_STATUS_TEXT = "Work...work!"

    CSS = """
    Screen {
        layout: vertical;
    }

    #startup {
        height: auto;
        padding: 1 2 0 2;
        color: #8bd5ff;
    }

    #conversation {
        height: 1fr;
        padding: 1 2;
        align: left bottom;
        scrollbar-size: 1 1;
    }

    #transcript {
        width: 1fr;
        height: auto;
        min-height: 1;
        border: none;
        padding: 0;
        margin: 0;
        background: $background;
    }

    #setup-label {
        height: auto;
        padding: 0 1;
    }

    #choices {
        height: auto;
        max-height: 8;
        display: none;
    }

    #composer {
        height: auto;
        min-height: 3;
        padding: 0 2;
    }

    #suggestions {
        height: auto;
        max-height: 6;
        color: $text-muted;
    }

    #prompt {
        width: 1fr;
    }

    #status {
        height: 1;
        color: $text-muted;
        background: $panel;
        padding: 0 2;
    }

    #processing {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "confirm_quit", "", show=False, priority=True),
        ("ctrl+d", "quit", "Quit"),
        ("escape", "clear_prompt", "Clear"),
    ]

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory | None,
        config_store: ProviderConfigStore,
        registry: ExtensionRegistry,
        processing_status_text: str | None = None,
        user_top_blank_lines: int = 1,
        user_bottom_blank_lines: int = 1,
        message_left_padding: int = 1,
    ) -> None:
        super().__init__()
        self.provider_factory = provider_factory
        self.config_store = config_store
        self.provider: ModelProvider | None = None
        self.config: ProviderConfig | None = None
        self.context = AgentContext()
        self.registry = registry
        self.setup_step: SetupStep | None = None
        self.pending_config: ProviderConfig | None = None
        self.pending_models: tuple[str, ...] = ()
        self.choice_values: list[object] = []
        self.choice_kind: SetupStep | None = None
        self.choice_generation = 0
        self.quit_confirmation_active = False
        self.quit_confirmation_label = ""
        self.quit_confirmation_password = False
        self.quit_confirmation_value = ""
        self.processing_status_text = (
            processing_status_text or self.PROCESSING_STATUS_TEXT
        )
        self.user_top_blank_lines = max(0, user_top_blank_lines)
        self.user_bottom_blank_lines = max(0, user_bottom_blank_lines)
        self.message_left_padding = max(0, message_left_padding)
        self.task_worker: Worker[str | ToolCall] | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            Text.assemble(
                ("peon", "#8bd5ff"),
                (" v0.1.0", "#808080"),
                ("\nescape interrupt · ctrl+c ask before exit · ctrl+d exit · / commands", "#808080"),
            ),
            id="startup",
        )
        with VerticalScroll(id="conversation"):
            yield ChatMessage(
                id="transcript",
                user_top_blank_lines=self.user_top_blank_lines,
                user_bottom_blank_lines=self.user_bottom_blank_lines,
                message_left_padding=self.message_left_padding,
            )
        yield Static("", id="setup-label")
        yield ListView(id="choices")
        yield ProcessingStatus(self.processing_status_text, id="processing")
        with Vertical(id="composer"):
            yield Static("", id="suggestions")
            yield PeonInput(
                placeholder="Ask Peon or type / for commands",
                id="prompt",
            )
        yield Static("", id="status")

    def on_mount(self) -> None:
        self.title = "Peon"
        configs = self.config_store.load_all()
        if len(configs) == 1:
            self._activate(configs[0])
        elif configs:
            self._show_choices(
                "saved-provider",
                "Select saved provider:",
                [
                    (config, f"{config.name} · {config.model or 'no model'}")
                    for config in configs
                ],
            )
        else:
            self._begin_provider_setup()

    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+c":
            self._handle_ctrl_c(event)
            return
        if self._is_non_input_focus() and event.character and event.character.isprintable():
            prompt = self.query_one("#prompt", PeonInput)
            prompt.focus()
            prompt.insert_text_at_cursor(event.character)
            event.stop()
            event.prevent_default()

    def _handle_ctrl_c(self, event: Key) -> None:
        if isinstance(self.focused, ChatMessage) and self.focused.selected_text:
            self.copy_to_clipboard(self.focused.selected_text)
            event.stop()
            event.prevent_default()
            return
        if isinstance(self.focused, PeonInput):
            event.stop()
            event.prevent_default()
            self.action_confirm_quit()

    def _is_non_input_focus(self) -> bool:
        return self.focused is not None and not isinstance(self.focused, PeonInput)

    def action_clear_prompt(self) -> None:
        if self.quit_confirmation_active:
            self._finish_quit_confirmation("")
            return
        if self.choice_kind is not None or self.setup_step is not None:
            self._cancel_selection()
            return
        self.query_one("#prompt", PeonInput).action_clear()

    def action_confirm_quit(self) -> None:
        if isinstance(self.focused, ChatMessage) and self.focused.selected_text:
            self.copy_to_clipboard(self.focused.selected_text)
            return
        if isinstance(self.focused, PeonInput):
            self._begin_quit_confirmation()

    def _write(self, text: str, *, role: str = "system") -> None:
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_message(text, role=role)
        conversation = self.query_one("#conversation", VerticalScroll)
        conversation.scroll_end(animate=False)

    def _set_processing(self, active: bool) -> None:
        self.query_one("#processing", ProcessingStatus).display = active
        self.query_one("#prompt", PeonInput).disabled = active

    def _run_task(self, task: str) -> str | ToolCall:
        assert self.provider is not None
        assert self.config is not None
        return run_task(
            task,
            self.provider,
            context=self.context,
            executor=self.registry,
            model=self.config.model,
        )

    def _start_task(self, task: str) -> None:
        self._set_processing(True)
        self.task_worker = cast(
            Worker[str | ToolCall],
            self.run_worker(
                lambda: self._run_task(task),
                name="peon-task",
                group="peon-task",
                exclusive=True,
                exit_on_error=False,
                thread=True,
            ),
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self.task_worker:
            return
        if event.state not in {
            WorkerState.CANCELLED,
            WorkerState.ERROR,
            WorkerState.SUCCESS,
        }:
            return
        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            if isinstance(result, ToolCall):
                self._write(
                    f"provider requested unhandled tool '{result.name}'",
                    role="system",
                )
            elif result is not None:
                self._write(result, role="assistant")
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            self._write(str(error or "task failed"), role="system")
        self.task_worker = None
        self._set_processing(False)
        self._set_status()

    def _set_status(self) -> None:
        if self.config is None:
            status = f"{Path.cwd()}  ·  setup required"
        else:
            status = (
                f"{Path.cwd()}  ·  {self.config.name}  ·  {self.config.model or 'no model'}"
                f"  ·  context {len(self.context.messages)}  ·  effort n/a  ·  tokens n/a"
            )
        self.query_one("#status", Static).update(status)

    def _show_choices(
        self,
        kind: SetupStep,
        title: str,
        choices: list[tuple[object, str]],
    ) -> None:
        self.setup_step = kind
        self.choice_kind = kind
        self.choice_values = [value for value, _label in choices]
        self.choice_generation += 1
        choice_prefix = f"choice-{self.choice_generation}"
        self.query_one("#setup-label", Static).update(title)
        list_view = self.query_one("#choices", ListView)
        list_view.clear()
        list_view.mount(
            *[
                ListItem(Label(label), id=f"{choice_prefix}-{index}")
                for index, (_value, label) in enumerate(choices)
            ]
        )
        if choices:
            list_view.index = 0
        list_view.display = True
        list_view.focus()

    def _hide_choices(self) -> None:
        self.query_one("#choices", ListView).display = False
        self.query_one("#setup-label", Static).update("")
        self.choice_values = []
        self.choice_kind = None
        self.query_one("#prompt", PeonInput).focus()

    def _cancel_selection(self) -> None:
        if self.choice_kind is not None:
            self._hide_choices()
        self._reset_setup()

    def _begin_provider_setup(self) -> None:
        self._show_choices(
            "provider",
            "Select provider to configure:",
            [
                (name, f"{index}. {label}")
                for index, (name, label) in enumerate(_PROVIDER_OPTIONS, 1)
            ],
        )
        self._set_status()

    def _show_logout_picker(self) -> None:
        configs = self.config_store.load_all()
        if not configs:
            self._write("No saved providers.")
            return
        self._show_choices(
            "logout-provider",
            "Select provider to remove:",
            [
                (config, f"{index}. {config.name} · {config.model or 'no model'}")
                for index, config in enumerate(configs, 1)
            ],
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id is None or not event.item.id.startswith("choice-"):
            return
        index = int(event.item.id.rsplit("-", maxsplit=1)[1])
        value = self.choice_values[index]
        kind = self.choice_kind
        self._hide_choices()
        if kind == "provider":
            self._start_provider_inputs(str(value))
        elif kind == "saved-provider":
            self._activate(value)  # type: ignore[arg-type]
        elif kind == "logout-provider":
            self._remove_provider(value)  # type: ignore[arg-type]
        elif kind == "model":
            self._finish_model_selection(str(value))

    def _start_provider_inputs(self, provider_name: str) -> None:
        self.setup_step = (
            "base-url" if provider_name == "openai-compatible" else "copilot-token"
        )
        self.pending_config = ProviderConfig(name=provider_name)
        prompt = (
            f"Base URL (default: {_DEFAULT_OPENAI_BASE_URL})"
            if provider_name == "openai-compatible"
            else "Copilot token (blank uses GITHUB_COPILOT_TOKEN)"
        )
        self.query_one("#setup-label", Static).update(prompt)
        prompt_input = self.query_one("#prompt", PeonInput)
        prompt_input.password = provider_name == "github-copilot"
        prompt_input.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        event.input.value = ""
        if self.quit_confirmation_active:
            self._finish_quit_confirmation(value)
            return
        if self.setup_step in {"base-url", "copilot-token", "api-key"}:
            self._handle_setup_input(value)
            return
        if not value:
            return
        if self.provider is None or self.config is None:
            self._begin_provider_setup()
            return
        if value.startswith("/"):
            self._handle_command(_resolve_command(value))
            return
        self._write(value, role="user")
        self._start_task(value)

    def _handle_setup_input(self, value: str) -> None:
        if self.pending_config is None:
            return
        if self.setup_step == "base-url":
            self.pending_config = ProviderConfig(
                name=self.pending_config.name,
                base_url=value or _DEFAULT_OPENAI_BASE_URL,
            )
            self.setup_step = "api-key"
            self._show_input_prompt("API key (blank for an unauthenticated endpoint)", password=True)
            return
        if self.setup_step == "api-key":
            self.pending_config = ProviderConfig(
                name=self.pending_config.name,
                base_url=self.pending_config.base_url,
                api_key=value or None,
            )
        elif self.setup_step == "copilot-token":
            self.pending_config = ProviderConfig(
                name=self.pending_config.name,
                copilot_token=value or None,
            )
        self._finish_provider_setup()

    def _show_input_prompt(self, text: str, *, password: bool = False) -> None:
        self.query_one("#setup-label", Static).update(text)
        prompt = self.query_one("#prompt", PeonInput)
        prompt.password = password
        prompt.focus()

    def _finish_provider_setup(self) -> None:
        if self.pending_config is None:
            return
        config = self.pending_config
        try:
            provider = (self.provider_factory or create_provider)(config)
            if config.name == "openai-compatible":
                models = self._discover_models(provider)
                if not models:
                    raise ProviderError("provider did not advertise any models")
                self.pending_models = models
                if len(models) == 1:
                    self._finish_model_selection(models[0])
                else:
                    self._show_choices(
                        "model",
                        "Select default model:",
                        [
                            (model, f"{index}. {model}")
                            for index, model in enumerate(models, 1)
                        ],
                    )
            else:
                self._complete_provider_setup(
                    ProviderConfig(
                        name=config.name,
                        model="gpt-4o",
                        copilot_token=config.copilot_token,
                    )
                )
        except (CommandError, ProviderError, ValueError) as caught:
            self._write(f"Provider setup failed: {caught}")
            self._reset_setup()

    def _discover_models(self, provider: ModelProvider) -> tuple[str, ...]:
        list_models = getattr(provider, "list_models", None)
        if not callable(list_models):
            return ()
        try:
            models = tuple(list_models())
        except ProviderError as caught:
            self._write(f"Model discovery failed: {caught}")
            return ()
        if not all(isinstance(model, str) and model.strip() for model in models):
            self._write("Provider returned invalid model IDs")
            return ()
        return models

    def _finish_model_selection(self, model: str) -> None:
        if self.pending_config is None:
            return
        config = ProviderConfig(
            name=self.pending_config.name,
            model=model,
            models=self.pending_models,
            base_url=self.pending_config.base_url,
            api_key=self.pending_config.api_key,
            copilot_token=self.pending_config.copilot_token,
        )
        self._complete_provider_setup(config)

    def _complete_provider_setup(self, config: ProviderConfig) -> None:
        try:
            provider = (self.provider_factory or create_provider)(config)
            self.config_store.save(config)
            self._activate(config, provider=provider)
        except (CommandError, ProviderError, OSError, ValueError) as caught:
            self._write(f"Provider setup failed: {caught}")
        self._reset_setup()

    def _activate(
        self,
        config: ProviderConfig,
        *,
        provider: ModelProvider | None = None,
    ) -> None:
        try:
            active_provider = provider or (self.provider_factory or create_provider)(config)
        except (CommandError, ProviderError, ValueError) as caught:
            self._write(f"Saved provider unavailable: {caught}")
            self._begin_provider_setup()
            return
        self.provider = active_provider
        self.config = config
        self._set_status()
        self.query_one("#prompt", PeonInput).focus()

    def _reset_setup(self) -> None:
        self.setup_step = None
        self.pending_config = None
        self.pending_models = ()
        self.query_one("#setup-label", Static).update("")
        self.query_one("#prompt", PeonInput).password = False
        self.query_one("#prompt", PeonInput).focus()

    def _begin_quit_confirmation(self) -> None:
        if self.quit_confirmation_active:
            return
        prompt = self.query_one("#prompt", PeonInput)
        label = self.query_one("#setup-label", Static)
        self.quit_confirmation_active = True
        self.quit_confirmation_label = str(label.renderable)
        self.quit_confirmation_password = prompt.password
        self.quit_confirmation_value = prompt.value
        prompt.value = ""
        prompt.password = False
        label.update("Exit Peon? [y/N]")
        prompt.focus()

    def _finish_quit_confirmation(self, value: str) -> None:
        if value.lower() in {"y", "yes"}:
            self.exit(0)
            return
        prompt = self.query_one("#prompt", PeonInput)
        label = self.query_one("#setup-label", Static)
        self.quit_confirmation_active = False
        prompt.password = self.quit_confirmation_password
        prompt.value = self.quit_confirmation_value
        label.update(self.quit_confirmation_label)
        prompt.focus()

    def _handle_command(self, command: str) -> None:
        name, _, argument = command.partition(" ")
        matches = [
            spec for spec, _description in _COMMAND_SPECS if spec.startswith(name.lower())
        ]
        if not matches:
            self._write(f"Unknown command: {name}")
            return
        resolved = matches[0]
        if resolved == "/quit":
            self.exit(0)
        elif resolved == "/logout":
            self._show_logout_picker()
        elif resolved == "/help":
            self._write("/provider /models /model /logout /tools /clear /help /quit")
        elif resolved == "/models":
            self._write(
                "Models: "
                + ", ".join(self.config.models if self.config else ())
            )
        elif resolved == "/model":
            self._show_model_picker(argument.strip())
        elif resolved == "/provider":
            self._begin_provider_setup()
        elif resolved == "/clear":
            self.context.messages.clear()
            self.query_one("#transcript", ChatMessage).clear_transcript()
            self._write("✓ New session started", role="success")
            self._set_status()
        elif resolved == "/tools":
            self._write("Tools: " + ", ".join(tool.name for tool in self.registry.tools))

    def _show_model_picker(self, argument: str) -> None:
        if self.config is None or not self.config.models:
            self._write("No saved models. Use /provider to discover models.")
            return
        if argument:
            self.pending_config = self.config
            self.pending_models = self.config.models
            try:
                model = _select_model(argument, self.config.models)
            except ValueError as caught:
                self._write(str(caught))
                return
            self._finish_model_selection(model)
            return
        self.pending_config = self.config
        self.pending_models = self.config.models
        self._show_choices(
            "model",
            "Select model:",
            [
                (model, f"{index}. {model}")
                for index, model in enumerate(self.config.models, 1)
            ],
        )

    def _remove_provider(self, config: ProviderConfig) -> None:
        try:
            self.config_store.delete(config)
        except OSError as caught:
            self._write(f"Could not remove provider: {caught}")
            return
        self._write(f"Removed provider: {config.name}")
        if self.config is not None and provider_id(self.config) == provider_id(config):
            remaining = self.config_store.load_all()
            self.provider = None
            self.config = None
            if remaining:
                self._activate(remaining[0])
            else:
                self._begin_provider_setup()
        else:
            self._set_status()


def _select_model(selection: str, models: tuple[str, ...]) -> str:
    if selection.isdigit():
        index = int(selection) - 1
        if 0 <= index < len(models):
            return models[index]
    if selection in models:
        return selection
    raise ValueError("select a model by number or exact model ID")


def run_textual_tui(
    *,
    provider_factory: ProviderFactory | None,
    output: object,
    error: object,
    registry: ExtensionRegistry,
    config_store: ProviderConfigStore,
    user_top_blank_lines: int = 1,
    user_bottom_blank_lines: int = 1,
    message_left_padding: int = 1,
) -> int:
    """Run the real terminal UI; output/error stay in the CLI signature."""
    del output, error
    app = TextualPeonApp(
        provider_factory=provider_factory,
        config_store=config_store,
        registry=registry,
        user_top_blank_lines=user_top_blank_lines,
        user_bottom_blank_lines=user_bottom_blank_lines,
        message_left_padding=message_left_padding,
    )
    app.run()
    return int(app.return_code or 0)
