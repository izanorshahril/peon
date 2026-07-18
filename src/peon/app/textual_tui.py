"""Textual renderer for Peon's minimal interactive mode."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace
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

from .cli import (
    CONFIG_SETTING_SPECS,
    CommandError,
    ProviderConfig,
    ProviderFactory,
    ProviderSettingSpec,
    REQUEST_FIELD_SETTING_SPECS,
    RESPONSE_FIELD_SETTING_SPECS,
    SavedModel,
    create_provider,
    saved_model_choices,
    select_saved_model,
    update_provider_setting,
)
from .config import (
    UI_SETTING_SPECS,
    ProviderConfigStore,
    load_ui_config,
    provider_id,
    save_ui_config,
    update_saved_provider,
    update_ui_setting,
)
from .commands import DEFAULT_COMMAND_CATALOG, CommandMatch

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
    ("custom", "Custom provider"),
)
def _format_setting_value(value: object, *, secret: bool = False) -> str:
    if secret and value:
        return "configured"
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _cycle_choice(
    current: str,
    choices: tuple[str, ...],
    direction: int,
) -> str:
    try:
        index = choices.index(current)
    except ValueError:
        index = 0
    return choices[(index + direction) % len(choices)]


SetupStep = Literal[
    "provider",
    "saved-provider",
    "logout-provider",
    "custom-name",
    "settings-root",
    "settings-provider-type",
    "settings-provider",
    "settings-profile",
    "settings-config",
    "settings-request",
    "settings-response",
    "settings-ui",
    "setting-value",
    "base-url",
    "api-key",
    "copilot-token",
    "model",
]


class PeonInput(Input):
    """Composer input with live slash-command hints and Escape clearing."""

    def on_key(self, event: Key) -> None:
        app = cast(TextualPeonApp, self.app)
        if event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            app.action_confirm_quit()
        elif event.key in {"up", "down"} and app.command_matches:
            app.move_command_selection(1 if event.key == "down" else -1)
            event.stop()
            event.prevent_default()
        elif event.key == "tab":
            if app.complete_selected_command():
                event.stop()
                event.prevent_default()

    def on_input_changed(self, event: Input.Changed) -> None:
        cast(TextualPeonApp, self.app).update_command_suggestions(event.value)

    def action_clear(self) -> None:
        cast(TextualPeonApp, self.app).dismiss_command_palette()

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
        user_message_color: str = USER_FOREGROUND,
        user_message_background: str = USER_BACKGROUND,
        assistant_message_color: str = "#e0e0e0",
        text_format: str = "normal",
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
        self.user_message_color = user_message_color
        self.user_message_background = user_message_background
        self.assistant_message_color = assistant_message_color
        self.text_format = text_format
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
                Style(
                    color=self.user_message_color,
                    bgcolor=self.user_message_background,
                )
            )
        elif role == "assistant":
            line.stylize(Style(color=self.assistant_message_color))
        elif role in {"system", "thinking"}:
            line.stylize(Style(color=self.THINKING_FOREGROUND, italic=True))
        elif role == "success":
            line.stylize(Style(color=self.SUCCESS_FOREGROUND))
        if role in {"user", "assistant"} and self.text_format != "normal":
            line.stylize(
                Style(
                    bold=self.text_format == "bold",
                    italic=self.text_format == "italic",
                )
            )
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
            role_style = Style(bgcolor=self.user_message_background)
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
        self.pending_setting_spec: ProviderSettingSpec | None = None
        self.pending_ui_setting: tuple[str, str, str] | None = None
        self.settings_return_kind: SetupStep | None = None
        self.pending_models: tuple[str, ...] = ()
        self.choice_values: list[object] = []
        self.choice_kind: SetupStep | None = None
        self.choice_generation = 0
        self.command_matches: tuple[CommandMatch, ...] = ()
        self.command_selected_index = 0
        self.quit_confirmation_active = False
        self.quit_confirmation_label = ""
        self.quit_confirmation_password = False
        self.quit_confirmation_value = ""
        self.processing_status_text = (
            processing_status_text or self.PROCESSING_STATUS_TEXT
        )
        stored_ui = load_ui_config(config_store)
        self.ui_config = replace(
            stored_ui,
            user_top_blank_lines=(
                user_top_blank_lines
                if user_top_blank_lines != 1
                else stored_ui.user_top_blank_lines
            ),
            user_bottom_blank_lines=(
                user_bottom_blank_lines
                if user_bottom_blank_lines != 1
                else stored_ui.user_bottom_blank_lines
            ),
            message_left_padding=(
                message_left_padding
                if message_left_padding != 1
                else stored_ui.message_left_padding
            ),
        )
        self.user_top_blank_lines = self.ui_config.user_top_blank_lines
        self.user_bottom_blank_lines = self.ui_config.user_bottom_blank_lines
        self.message_left_padding = self.ui_config.message_left_padding
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
                user_message_color=self.ui_config.user_message_color,
                user_message_background=self.ui_config.user_message_background,
                assistant_message_color=self.ui_config.assistant_message_color,
                text_format=self.ui_config.text_format,
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
        self._apply_ui_config()
        config = self.config_store.load()
        if config is not None:
            self._activate(config)
        else:
            self._begin_provider_setup()

    def _apply_ui_config(self) -> None:
        self.screen.styles.background = self.ui_config.background_color
        conversation = self.query_one("#conversation", VerticalScroll)
        conversation.styles.background = self.ui_config.chat_area_color
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.styles.background = self.ui_config.chat_area_color
        transcript.user_top_blank_lines = self.ui_config.user_top_blank_lines
        transcript.user_bottom_blank_lines = self.ui_config.user_bottom_blank_lines
        transcript.message_left_padding = self.ui_config.message_left_padding
        transcript.user_message_color = self.ui_config.user_message_color
        transcript.user_message_background = self.ui_config.user_message_background
        transcript.assistant_message_color = self.ui_config.assistant_message_color
        transcript.text_format = self.ui_config.text_format
        transcript.refresh()

    def on_key(self, event: Key) -> None:
        if event.key == "ctrl+c":
            self._handle_ctrl_c(event)
            return
        if event.key in {"left", "right"} and self._adjust_selected_setting(
            1 if event.key == "right" else -1
        ):
            event.stop()
            event.prevent_default()
            return
        if self.choice_kind is not None and event.character and event.character.isdigit():
            index = int(event.character) - 1
            if 0 <= index < len(self.choice_values):
                event.stop()
                event.prevent_default()
                self._select_choice(index)
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

    def update_command_suggestions(self, value: str) -> None:
        matches: tuple[CommandMatch, ...] = ()
        if value.startswith("/"):
            matches = DEFAULT_COMMAND_CATALOG.search(value)
            if not matches and any(character.isspace() for character in value):
                command_head = value.split(maxsplit=1)[0]
                matches = DEFAULT_COMMAND_CATALOG.search(command_head)
        selected_id = (
            self.command_matches[self.command_selected_index].command.id
            if self.command_matches
            and self.command_selected_index < len(self.command_matches)
            else None
        )
        self.command_matches = matches
        self.command_selected_index = next(
            (
                index
                for index, match in enumerate(matches)
                if match.command.id == selected_id
            ),
            0,
        )
        self._render_command_suggestions()

    def _render_command_suggestions(self) -> None:
        rendered = Text()
        for index, match in enumerate(self.command_matches):
            if index:
                rendered.append("\n")
            selected = index == self.command_selected_index
            rendered.append("> " if selected else "  ", style="dim")
            command = match.command
            rendered.append(command.name, style="bold reverse" if selected else "bold")
            rendered.append(f"  {command.description}", style="dim")
            if command.candidate_names:
                rendered.append(
                    f"  (also: {', '.join(command.candidate_names)})",
                    style="dim italic",
                )
            if match.is_reserved:
                rendered.append("  [reserved]", style="yellow")
        self.query_one("#suggestions", Static).update(rendered)

    def move_command_selection(self, direction: int) -> None:
        if not self.command_matches:
            return
        self.command_selected_index = (
            self.command_selected_index + direction
        ) % len(self.command_matches)
        self._render_command_suggestions()

    def complete_selected_command(self) -> bool:
        if not self.command_matches:
            return False
        command = self.command_matches[self.command_selected_index].command.name
        prompt = self.query_one("#prompt", PeonInput)
        if prompt.value == command:
            return False
        prompt.value = command
        prompt.cursor_position = len(command)
        return True

    def dismiss_command_palette(self) -> None:
        self.command_matches = ()
        self.command_selected_index = 0
        self.query_one("#suggestions", Static).update("")

    def action_clear_prompt(self) -> None:
        if self.quit_confirmation_active:
            self._finish_quit_confirmation("")
            return
        if self.command_matches:
            self.dismiss_command_palette()
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
        self._select_choice(index)

    def _select_choice(self, index: int) -> None:
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
            self._finish_model_selection(cast(SavedModel, value))
        elif kind == "settings-root":
            self._select_settings_root(str(value))
        elif kind == "settings-provider-type":
            self._show_settings_providers(str(value))
        elif kind == "settings-provider":
            self.pending_config = cast(ProviderConfig, value)
            self._show_settings_profile()
        elif kind == "settings-profile":
            self._select_settings_profile(str(value))
        elif kind in {"settings-config", "settings-request", "settings-response"}:
            self._select_provider_setting(cast(ProviderSettingSpec, value), kind)
        elif kind == "settings-ui":
            self._select_ui_setting(cast(tuple[str, str, str], value))

    def _show_settings(self) -> None:
        self._show_choices(
            "settings-root",
            "Settings:",
            [
                ("ui", "1. UI"),
                ("saved-provider", "2. Saved provider"),
                ("add-provider", "3. Add provider"),
            ],
        )

    def _select_settings_root(self, section: str) -> None:
        if section == "ui":
            self._show_ui_settings()
        elif section == "add-provider":
            self._begin_provider_setup()
        else:
            configs = self.config_store.load_all()
            available = {config.provider_type or config.name for config in configs}
            choices: list[tuple[object, str]] = [
                (provider_type, f"{index}. {label}")
                for index, (provider_type, label) in enumerate(
                    (
                        option
                        for option in _PROVIDER_OPTIONS
                        if option[0] in available
                    ),
                    1,
                )
            ]
            if not choices:
                self._write("No saved providers.")
                self._show_settings()
                return
            self._show_choices(
                "settings-provider-type",
                "Select provider type:",
                choices,
            )

    def _show_settings_providers(self, provider_type: str) -> None:
        configs = tuple(
            config
            for config in self.config_store.load_all()
            if (config.provider_type or config.name) == provider_type
        )
        self._show_choices(
            "settings-provider",
            "Select saved provider:",
            [
                (config, f"{index}. {config.name}")
                for index, config in enumerate(configs, 1)
            ],
        )

    def _show_settings_profile(self) -> None:
        if self.pending_config is None:
            self._show_settings()
            return
        sections = [("name", "Name"), ("config", "Config")]
        if (self.pending_config.provider_type or self.pending_config.name) == "custom":
            sections.extend(
                [("request", "Request fields"), ("response", "Response fields")]
            )
        self._show_choices(
            "settings-profile",
            f"Provider settings: {self.pending_config.name}",
            [
                (key, f"{index}. {label}")
                for index, (key, label) in enumerate(sections, 1)
            ],
        )

    def _select_settings_profile(self, section: str) -> None:
        if section == "name":
            self._start_provider_setting_input(
                ProviderSettingSpec("name", "Name", "name", "text"),
                "settings-profile",
            )
        elif section == "config":
            self._show_provider_settings_category("settings-config")
        elif section == "request":
            self._show_provider_settings_category("settings-request")
        else:
            self._show_provider_settings_category("settings-response")

    def _settings_specs(self, kind: SetupStep) -> tuple[ProviderSettingSpec, ...]:
        if kind == "settings-config":
            return CONFIG_SETTING_SPECS
        if kind == "settings-request":
            return REQUEST_FIELD_SETTING_SPECS
        return RESPONSE_FIELD_SETTING_SPECS

    def _show_provider_settings_category(
        self,
        kind: SetupStep,
        *,
        focus_key: str | None = None,
    ) -> None:
        if self.pending_config is None:
            self._show_settings()
            return
        specs = self._settings_specs(kind)
        labels = {
            "settings-config": "Config",
            "settings-request": "Request fields",
            "settings-response": "Response fields",
        }
        self._show_choices(
            kind,
            f"{self.pending_config.name} · {labels[kind]}",
            [
                (
                    spec,
                    f"{index}. {spec.label:<34} {_format_setting_value(getattr(self.pending_config, spec.field_name), secret=spec.value_kind == 'secret')}",
                )
                for index, spec in enumerate(specs, 1)
            ],
        )
        if focus_key is not None:
            focused_index = next(
                (index for index, spec in enumerate(specs) if spec.key == focus_key),
                0,
            )
            self.query_one("#choices", ListView).index = focused_index

    def _select_provider_setting(
        self,
        spec: ProviderSettingSpec,
        return_kind: SetupStep,
    ) -> None:
        if self.pending_config is None:
            return
        current = getattr(self.pending_config, spec.field_name)
        if spec.value_kind == "toggle":
            self._apply_provider_setting(spec, str(not bool(current)).lower(), return_kind)
        elif spec.value_kind == "choice":
            self._apply_provider_setting(
                spec,
                _cycle_choice(_format_setting_value(current), spec.choices, 1),
                return_kind,
            )
        else:
            self._start_provider_setting_input(spec, return_kind)

    def _start_provider_setting_input(
        self,
        spec: ProviderSettingSpec,
        return_kind: SetupStep | None,
    ) -> None:
        self.pending_setting_spec = spec
        self.pending_ui_setting = None
        self.settings_return_kind = return_kind
        self.setup_step = "setting-value"
        choices = f" ({'|'.join(spec.choices)})" if spec.choices else ""
        self._show_input_prompt(
            f"{spec.label}{choices}:",
            password=spec.value_kind == "secret",
        )

    def _show_ui_settings(self, *, focus_key: str | None = None) -> None:
        self._show_choices(
            "settings-ui",
            "UI settings:",
            [
                (
                    spec,
                    f"{index}. {label:<28} {getattr(self.ui_config, field_name)}",
                )
                for index, spec in enumerate(UI_SETTING_SPECS, 1)
                for _key, label, field_name in (spec,)
            ],
        )
        if focus_key is not None:
            focused_index = next(
                (index for index, spec in enumerate(UI_SETTING_SPECS) if spec[0] == focus_key),
                0,
            )
            self.query_one("#choices", ListView).index = focused_index

    def _select_ui_setting(self, spec: tuple[str, str, str]) -> None:
        key, label, field_name = spec
        current = getattr(self.ui_config, field_name)
        if field_name == "text_format":
            self._apply_ui_setting(
                key,
                _cycle_choice(str(current), ("normal", "bold", "italic"), 1),
            )
            return
        self.pending_setting_spec = None
        self.pending_ui_setting = spec
        self.settings_return_kind = "settings-ui"
        self.setup_step = "setting-value"
        self._show_input_prompt(f"{label}:")

    def _apply_provider_setting(
        self,
        spec: ProviderSettingSpec,
        value: str,
        return_kind: SetupStep | None,
    ) -> None:
        if self.pending_config is None:
            return
        previous = self.pending_config
        try:
            config = update_provider_setting(previous, spec.key, value)
            provider = (self.provider_factory or create_provider)(config)
            update_saved_provider(self.config_store, previous, config)
        except (CommandError, ProviderError, OSError, ValueError) as caught:
            self._write(f"Setting update failed: {caught}")
            if return_kind in {
                "settings-config",
                "settings-request",
                "settings-response",
            }:
                self._show_provider_settings_category(return_kind, focus_key=spec.key)
            elif return_kind == "settings-profile":
                self._show_settings_profile()
            else:
                self._reset_setup()
            return
        self.pending_config = config
        self.provider = provider
        self.config = config
        self._set_status()
        if return_kind in {
            "settings-config",
            "settings-request",
            "settings-response",
        }:
            self._show_provider_settings_category(return_kind, focus_key=spec.key)
        elif return_kind == "settings-profile":
            self._show_settings_profile()
        else:
            self._reset_setup()

    def _apply_ui_setting(self, setting: str, value: str) -> None:
        try:
            self.ui_config = update_ui_setting(self.ui_config, setting, value)
            save_ui_config(self.config_store, self.ui_config)
        except (OSError, ValueError) as caught:
            self._write(f"UI setting update failed: {caught}")
        self._apply_ui_config()
        self._show_ui_settings(focus_key=setting)

    def _adjust_selected_setting(self, direction: int) -> bool:
        kind = self.choice_kind
        if kind not in {
            "settings-config",
            "settings-request",
            "settings-response",
            "settings-ui",
        }:
            return False
        index = self.query_one("#choices", ListView).index
        if index is None or not 0 <= index < len(self.choice_values):
            return False
        if kind == "settings-ui":
            key, _label, field_name = cast(tuple[str, str, str], self.choice_values[index])
            current = getattr(self.ui_config, field_name)
            if field_name == "text_format":
                value = _cycle_choice(
                    str(current),
                    ("normal", "bold", "italic"),
                    direction,
                )
            elif isinstance(current, int):
                value = str(max(0, min(8, current + direction)))
            else:
                return False
            self._apply_ui_setting(key, value)
            return True
        spec = cast(ProviderSettingSpec, self.choice_values[index])
        if self.pending_config is None:
            return False
        current = getattr(self.pending_config, spec.field_name)
        if spec.value_kind == "toggle":
            value = str(not bool(current)).lower()
        elif spec.value_kind == "choice":
            value = _cycle_choice(
                _format_setting_value(current),
                spec.choices,
                direction,
            )
        elif spec.value_kind == "temperature":
            value = str(round(max(0.0, min(1.0, float(current or 0) + 0.1 * direction)), 1))
        elif spec.value_kind == "integer" and current is not None:
            value = str(max(1, int(current) + direction))
        else:
            return False
        self._apply_provider_setting(spec, value, kind)
        return True

    def _start_provider_inputs(self, provider_name: str) -> None:
        if provider_name == "custom":
            self.setup_step = "custom-name"
            self.pending_config = ProviderConfig(
                name="custom provider",
                provider_type="custom",
            )
            prompt = "Custom provider name (default: custom provider)"
        else:
            self.setup_step = (
                "base-url"
                if provider_name == "openai-compatible"
                else "copilot-token"
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
        if self.quit_confirmation_active:
            event.input.value = ""
            self._finish_quit_confirmation(value)
            return
        if self.setup_step in {
            "custom-name",
            "base-url",
            "copilot-token",
            "api-key",
            "setting-value",
        }:
            event.input.value = ""
            self._handle_setup_input(value)
            return
        if not value:
            event.input.value = ""
            return
        if self.provider is None or self.config is None:
            event.input.value = ""
            self._begin_provider_setup()
            return
        if value.startswith("/"):
            invocation = DEFAULT_COMMAND_CATALOG.resolve(value)
            selected = (
                self.command_matches[self.command_selected_index]
                if self.command_matches
                else None
            )
            event.input.value = ""
            self.dismiss_command_palette()
            if selected is not None and (
                invocation is None or not invocation.is_direct
            ):
                _name, separator, argument = value.partition(" ")
                selected_value = (
                    f"{selected.command.name}{separator}{argument}"
                    if separator
                    else selected.command.name
                )
                self._handle_command(selected_value)
            else:
                self._handle_command(value)
            return
        event.input.value = ""
        self._write(value, role="user")
        self._start_task(value)

    def _handle_setup_input(self, value: str) -> None:
        if self.setup_step == "setting-value":
            self.query_one("#prompt", PeonInput).password = False
            if self.pending_ui_setting is not None:
                self._apply_ui_setting(self.pending_ui_setting[0], value)
            elif self.pending_setting_spec is not None and self.pending_config is not None:
                self._apply_provider_setting(
                    self.pending_setting_spec,
                    value,
                    self.settings_return_kind,
                )
            else:
                self._reset_setup()
            return
        if self.pending_config is None:
            return
        if self.setup_step == "custom-name":
            self.pending_config = ProviderConfig(
                name=value or "custom provider",
                provider_type="custom",
            )
            self.setup_step = "base-url"
            self._show_input_prompt("Proxy URL:")
            return
        if self.setup_step == "base-url":
            self.pending_config = ProviderConfig(
                name=self.pending_config.name,
                provider_type=self.pending_config.provider_type,
                base_url=(
                    value
                    or (
                        _DEFAULT_OPENAI_BASE_URL
                        if self.pending_config.provider_type is None
                        else ""
                    )
                ),
            )
            self.setup_step = "api-key"
            self._show_input_prompt("API key (blank for an unauthenticated endpoint)", password=True)
            return
        if self.setup_step == "api-key":
            self.pending_config = ProviderConfig(
                name=self.pending_config.name,
                provider_type=self.pending_config.provider_type,
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
            provider_type = config.provider_type or config.name
            if provider_type in {"openai-compatible", "custom"}:
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
                        provider_type=config.provider_type,
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

    def _finish_model_selection(self, selection: SavedModel | str) -> None:
        if isinstance(selection, SavedModel):
            config = replace(selection.config, model=selection.model)
        else:
            if self.pending_config is None:
                return
            config = replace(
                self.pending_config,
                model=selection,
                models=self.pending_models,
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
        self.pending_setting_spec = None
        self.pending_ui_setting = None
        self.settings_return_kind = None
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
        name = command.split(maxsplit=1)[0]
        invocation = DEFAULT_COMMAND_CATALOG.resolve(command)
        if invocation is None:
            self._write(f"Unknown command: {name}")
            return
        definition = invocation.command
        if definition.setting_key is not None:
            self._handle_provider_setting_command(
                definition.setting_key,
                invocation.argument,
            )
        elif definition.availability == "reserved":
            self._write(f"{definition.name} is reserved and is not available yet.")
        elif definition.id == "quit":
            self.exit(0)
        elif definition.id == "logout":
            self._show_logout_picker()
        elif definition.id == "help":
            self._write(DEFAULT_COMMAND_CATALOG.help_text())
        elif definition.id == "model" and name.casefold() == "/models" and not invocation.argument:
            choices = saved_model_choices(self.config_store.load_all())
            self._write("Models: " + ", ".join(choice.label for choice in choices))
        elif definition.id == "model":
            self._show_model_picker(invocation.argument)
        elif definition.id == "provider":
            self._begin_provider_setup()
        elif definition.id == "settings":
            self._show_settings()
        elif definition.id == "new":
            self.context.messages.clear()
            self.query_one("#transcript", ChatMessage).clear_transcript()
            self._write("✓ New session started", role="success")
            self._set_status()
        elif definition.id == "tools":
            self._write("Tools: " + ", ".join(tool.name for tool in self.registry.tools))

    def _handle_provider_setting_command(self, setting: str, value: str) -> None:
        if self.config is None:
            self._write("No active provider.")
            return
        spec = (
            ProviderSettingSpec("name", "Name", "name", "text")
            if setting == "name"
            else next(spec for spec in CONFIG_SETTING_SPECS if spec.key == setting)
        )
        self.pending_config = self.config
        current = getattr(self.config, spec.field_name)
        if not value and spec.value_kind == "toggle":
            value = str(not bool(current)).lower()
        elif not value and spec.value_kind == "choice":
            value = _cycle_choice(
                _format_setting_value(current),
                spec.choices,
                1,
            )
        if value:
            self._apply_provider_setting(spec, value, None)
        else:
            self._start_provider_setting_input(spec, None)

    def _show_model_picker(self, argument: str) -> None:
        choices = saved_model_choices(self.config_store.load_all())
        if not choices:
            self._write("No saved models. Use /provider to discover models.")
            return
        if argument:
            try:
                choice = select_saved_model(argument, choices)
            except CommandError as caught:
                self._write(str(caught))
                return
            self._finish_model_selection(choice)
            return
        self._show_choices(
            "model",
            "Select model:",
            [
                (choice, f"{index}. {choice.label}")
                for index, choice in enumerate(choices, 1)
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
