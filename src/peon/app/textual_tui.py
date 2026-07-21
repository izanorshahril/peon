"""Textual renderer for Peon's minimal interactive mode."""

from __future__ import annotations

import json
import time
from pathlib import Path
from dataclasses import dataclass, replace
from typing import Literal, cast

from rich.color import Color as RichColor
from rich.console import Console
from rich.markdown import Markdown
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.document._document import Selection
from textual.events import Key, MouseDown, MouseMove, MouseUp
from textual.strip import Strip
from textual.worker import Worker, WorkerState
from textual.widgets import Input, Static, TextArea
from textual.containers import VerticalScroll

from peon.agent import (
    AgentContext,
    ModelProvider,
    ToolCall,
    ToolExecutionContext,
    Usage,
)
from peon.ai import ProviderError
from peon.extensions import ExtensionRegistry, discover_skill_names

from .cli import (
    CommandError,
    ProviderConfig,
    ProviderFactory,
    ProviderSettingSpec,
    REQUEST_FIELD_SETTING_SPECS,
    RESPONSE_FIELD_SETTING_SPECS,
    SavedModel,
    create_provider,
    cycle_reasoning_effort,
    provider_config_setting_specs,
    reasoning_effort_choices,
    saved_model_choices,
    select_saved_model,
    update_provider_setting,
)
from .config import (
    UI_SETTING_SPECS,
    GENERAL_SETTING_SPECS,
    SHORTCUT_SETTING_SPECS,
    ProviderConfigStore,
    filter_tool_executor,
    load_ui_config,
    provider_id,
    save_ui_config,
    update_saved_provider,
    update_general_setting,
    update_shortcut_setting,
    update_tool_setting,
    update_ui_setting,
)
from .sessions import (
    JsonlSessionStore,
    MemorySessionStore,
    SessionRecord,
    SessionStore,
    SessionStoreError,
    create_session,
    discard_empty_session,
    format_session_info,
    format_session_metadata,
    format_session_summary,
    merge_usage,
    select_session,
    session_first_prompt,
    session_interaction_count,
)
from .coding_session import MessageEvent, SessionEvent, TurnResult
from .session_controller import PromptIntent, SessionController
from .resources import (
    ResourceInventory,
    apply_resource_prompt,
    conversation_messages_without_resource_prompt,
    load_skill_into_context,
)
from .commands import (
    DEFAULT_COMMAND_CATALOG,
    CommandDefinition,
    CommandMatch,
)

_DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_ESCAPE_REPEAT_DELAY = 0.3
_ESCAPE_REPEAT_WINDOW = 0.75
_MARKDOWN_CONSOLE = Console(width=4096)
_COLLAPSED_TOOL_PREVIEW_LINES = 5
_STARTUP_SECTION_COLOR = "#f2c94c"
_STARTUP_TEXT_COLOR = "#808080"


def _render_startup(resources: ResourceInventory | None) -> Text:
    rendered = Text.assemble(
        ("peon", "#8bd5ff"),
        (" v0.2.0", _STARTUP_TEXT_COLOR),
        (
            "\nescape interrupt · ctrl+c/ctrl+d clear/exit · / commands · ! bash",
            _STARTUP_TEXT_COLOR,
        ),
    )
    if resources is None:
        return rendered
    rendered.append("\n\n")
    for index, line in enumerate(resources.startup_summary()):
        if index:
            rendered.append("\n")
        rendered.append(
            line,
            style=(
                _STARTUP_SECTION_COLOR
                if line in {"[Context]", "[Skills]"}
                else _STARTUP_TEXT_COLOR
            ),
        )
    return rendered


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


def _as_rich_style(value: object) -> Style | None:
    """Normalize Textual and Rich segment styles for Rich composition."""
    if value is None:
        return None
    if isinstance(value, Style):
        return value
    if isinstance(value, RichColor):
        return Style(color=value)
    rich_color = getattr(value, "rich_color", None)
    return Style(color=rich_color) if isinstance(rich_color, RichColor) else None


def _format_tool_call(tool_call: ToolCall) -> Text:
    """Render a compact, selectable tool label with semantic styles."""
    rendered = Text(end="")
    if tool_call.name == "bash":
        command = tool_call.arguments.get("command")
        rendered.append("$ ", style=Style(color="#f0f0f0", bold=True))
        rendered.append(
            str(command) if command else "...",
            style=Style(color="#f0f0f0", bold=True),
        )
        timeout = tool_call.arguments.get("timeout")
        if timeout is not None:
            rendered.append(f" (timeout {timeout}s)", style=Style(color="#808080"))
        return rendered
    rendered.append(
        tool_call.name,
        style=Style(color="#f0f0f0", bold=True),
    )
    if not tool_call.arguments:
        return rendered

    arguments = dict(tool_call.arguments)
    path_value = arguments.pop("path", arguments.pop("file_path", None))
    if isinstance(path_value, str) and path_value:
        rendered.append(" ")
        rendered.append(
            path_value,
            style=Style(
                color="#8bd5ff",
                link=Path(path_value).expanduser().resolve().as_uri(),
            ),
        )

    parameters: list[tuple[str, str]] = []
    for name in sorted(arguments):
        if name in {"detail", "details"}:
            continue
        try:
            value = json.dumps(
                arguments[name],
                ensure_ascii=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            value = str(arguments[name])
        parameters.append((name, value))
    if parameters:
        rendered.append(" " if path_value else ": ")
        for index, (name, value) in enumerate(parameters):
            if index:
                rendered.append(" ")
            rendered.append(
                f"{name}={value}",
                style=Style(color="#d6b37a"),
            )
    return rendered


@dataclass(frozen=True, slots=True)
class _TranscriptBlock:
    role: str
    text: str
    call_text: Text | None = None
    tool_call_id: str | None = None
    rich_text: Text | None = None


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
    "settings-general",
    "settings-shortcuts",
    "settings-tools",
    "session",
    "setting-value",
    "base-url",
    "api-key",
    "copilot-token",
    "model",
]


@dataclass
class _ChoiceState:
    kind: SetupStep
    title: str
    all_values: list[object]
    all_labels: list[str]
    all_search_text: list[str]
    values: list[object]
    labels: list[str]
    query: str
    selected_index: int


class PeonInput(Input):
    """Composer input with live slash-command hints and Escape clearing."""

    COMPONENT_CLASSES = Input.COMPONENT_CLASSES | {"input--selection"}
    BINDINGS = [
        *Input.BINDINGS,
        Binding("ctrl+c", "clear_input", "", show=False, priority=True),
    ]
    selection_start = 0
    _selecting = False

    DEFAULT_CSS = """
    PeonInput > .input--selection {
        background: $input-selection-background;
    }
    """

    @property
    def selected_text(self) -> str:
        start, end = sorted((self.selection_start, self.cursor_position))
        return self.value[start:end]

    def _watch_cursor_position(self) -> None:
        super()._watch_cursor_position()
        if not self._selecting:
            self.selection_start = self.cursor_position

    def select_range(self, start: int, end: int) -> None:
        self._selecting = True
        try:
            self.selection_start = max(0, min(start, len(self.value)))
            self.cursor_position = max(0, min(end, len(self.value)))
        finally:
            self._selecting = False
        self.refresh()

    @property
    def _value(self) -> Text:
        value = super()._value
        if not self.password and self.selected_text:
            start, end = sorted((self.selection_start, self.cursor_position))
            value.stylize(
                self.get_component_rich_style("input--selection"),
                start,
                end,
            )
        return value

    def _event_index(self, event: MouseDown | MouseMove) -> int:
        offset = event.get_content_offset(self)
        if offset is None:
            return self.cursor_position
        target_cell = max(0, offset.x + self.view_position)
        for index in range(len(self.value)):
            if self._position_to_cell(index + 1) > target_cell:
                return index
        return len(self.value)

    async def _on_mouse_down(self, event: MouseDown) -> None:
        if event.button == 3:
            if self.selected_text:
                cast(TextualPeonApp, self.app).copy_to_clipboard(self.selected_text)
            event.stop()
            event.prevent_default()
            return
        self.focus()
        self.cursor_position = self._event_index(event)
        self.selection_start = self.cursor_position
        self._selecting = True
        self.capture_mouse()
        await super()._on_mouse_down(event)

    async def _on_mouse_move(self, event: MouseMove) -> None:
        if self._selecting:
            self.cursor_position = self._event_index(event)
            self.refresh()

    async def _on_mouse_up(self, event: MouseUp) -> None:
        if self._selecting:
            self._selecting = False
            self.release_mouse()
        await super()._on_mouse_up(event)

    def insert_text_at_cursor(self, text: str) -> None:
        if self.selected_text:
            start, end = sorted((self.selection_start, self.cursor_position))
            self.value = self.value[:start] + self.value[end:]
            self.cursor_position = start
        super().insert_text_at_cursor(text)
        self.selection_start = self.cursor_position

    def clear(self) -> None:
        super().clear()
        self.selection_start = 0

    def on_key(self, event: Key) -> None:
        app = cast(TextualPeonApp, self.app)
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            app.action_clear_prompt()
        elif app.shortcut_matches(event.key, "thinking"):
            event.stop()
            event.prevent_default()
            app.action_toggle_thinking()
        elif app.shortcut_matches(event.key, "reasoning"):
            event.stop()
            event.prevent_default()
            app.action_cycle_reasoning()
        elif app.shortcut_matches(event.key, "tools"):
            event.stop()
            event.prevent_default()
            app.action_toggle_tools()
        elif event.key == "ctrl+c":
            event.stop()
            event.prevent_default()
            app.action_clear_input()
        elif app.choice_kind is not None and event.key in {"up", "down"}:
            app.move_choice_selection(1 if event.key == "down" else -1)
            event.stop()
            event.prevent_default()
        elif app.choice_kind is not None and event.key in {"enter", "space"}:
            app.select_current_choice()
            event.stop()
            event.prevent_default()
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

    def action_clear_input(self) -> None:
        cast(TextualPeonApp, self.app).action_clear_input()

    def action_confirm_quit(self) -> None:
        cast(TextualPeonApp, self.app).action_confirm_quit()


class ChoiceSearchInput(Input):
    """Search field for the focused picker; navigation stays app-owned."""

    def on_key(self, event: Key) -> None:
        app = cast(TextualPeonApp, self.app)
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            app.action_clear_prompt()
        elif app.shortcut_matches(event.key, "thinking"):
            event.stop()
            event.prevent_default()
            app.action_toggle_thinking()
        elif app.shortcut_matches(event.key, "reasoning"):
            event.stop()
            event.prevent_default()
            app.action_cycle_reasoning()
        elif app.shortcut_matches(event.key, "tools"):
            event.stop()
            event.prevent_default()
            app.action_toggle_tools()
        elif event.key in {"up", "down"}:
            app.move_choice_selection(1 if event.key == "down" else -1)
            event.stop()
            event.prevent_default()
        elif event.key in {"enter", "space"}:
            app.select_current_choice()
            event.stop()
            event.prevent_default()
        elif event.character and event.character.isdigit():
            app.select_choice_number(int(event.character))
            event.stop()
            event.prevent_default()


class ChatMessage(TextArea):
    """Single selectable transcript surface with role-aware line styling."""

    USER_BACKGROUND = "#3a3a44"
    USER_FOREGROUND = "#c4c4c4"
    THINKING_FOREGROUND = "#808080"
    SUCCESS_FOREGROUND = "#8bd5ff"
    TOOL_FOREGROUND = "#d6b37a"
    TOOL_BACKGROUND = "#283228"
    TOOL_OUTPUT_FOREGROUND = "#808080"

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
        system_text_format: str = "normal",
        tool_message_background: str = TOOL_BACKGROUND,
        tool_output_color: str = TOOL_OUTPUT_FOREGROUND,
        render_tool_markdown: bool = False,
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
        self._blocks: list[_TranscriptBlock] = []
        self.thinking_visible = True
        self.tools_expanded = False
        self._snapping_selection = False
        self.user_top_blank_lines = max(0, user_top_blank_lines)
        self.user_bottom_blank_lines = max(0, user_bottom_blank_lines)
        self.message_left_padding = max(0, message_left_padding)
        self.user_message_color = user_message_color
        self.user_message_background = user_message_background
        self.assistant_message_color = assistant_message_color
        self.text_format = text_format
        self.system_text_format = system_text_format
        self.tool_message_background = tool_message_background
        self.tool_output_color = tool_output_color
        self.render_tool_markdown = render_tool_markdown
        self.display = False
        if text:
            self.append_message(text, role=role)

    def append_message(
        self,
        text: str | Text,
        *,
        role: str,
        tool_call_id: str | None = None,
    ) -> None:
        if role == "tool-call" and isinstance(text, Text):
            self._blocks.append(
                _TranscriptBlock(
                    role=role,
                    text="",
                    call_text=text.copy(),
                    tool_call_id=tool_call_id,
                )
            )
            self._refresh_blocks()
            return
        plain_text = text.plain if isinstance(text, Text) else text
        rich_text = text.copy() if isinstance(text, Text) else None
        if role == "tool" and self._blocks:
            previous = self._blocks[-1]
            if previous.role == "tool-call" and (
                previous.tool_call_id is None
                or tool_call_id is None
                or previous.tool_call_id == tool_call_id
            ):
                self._blocks[-1] = _TranscriptBlock(
                    role="tool-message",
                    text=plain_text,
                    call_text=previous.call_text or Text(previous.text, end=""),
                    tool_call_id=tool_call_id or previous.tool_call_id,
                )
                self._refresh_blocks()
                return
            if previous.role == "tool-message" and (
                previous.tool_call_id is None
                or tool_call_id is None
                or previous.tool_call_id == tool_call_id
            ):
                self._blocks[-1] = _TranscriptBlock(
                    role="tool-message",
                    text=plain_text,
                    call_text=previous.call_text,
                    tool_call_id=tool_call_id or previous.tool_call_id,
                )
                self._refresh_blocks()
                return
        self._blocks.append(
            _TranscriptBlock(
                role=role,
                text=plain_text,
                tool_call_id=tool_call_id,
                rich_text=rich_text,
            )
        )
        self._refresh_blocks()

    def append_tool_output(self, text: str) -> None:
        """Update the active tool block with non-persisted live output."""
        if not text:
            return
        if self._blocks and self._blocks[-1].role == "tool-call":
            previous = self._blocks[-1]
            self._blocks[-1] = _TranscriptBlock(
                role="tool-message",
                text=text,
                call_text=previous.call_text or Text(previous.text, end=""),
                tool_call_id=previous.tool_call_id,
            )
        elif self._blocks and self._blocks[-1].role == "tool-message":
            previous = self._blocks[-1]
            self._blocks[-1] = _TranscriptBlock(
                role="tool-message",
                text=previous.text + text,
                call_text=previous.call_text,
                tool_call_id=previous.tool_call_id,
            )
        else:
            self._blocks.append(_TranscriptBlock(role="tool-message", text=text))
        self._refresh_blocks()

    def _refresh_blocks(self) -> None:
        styled_lines: list[Text] = []
        line_roles: list[str] = []
        has_rendered_block = False
        for block in self._blocks:
            role = block.role
            text = block.text
            if role == "thinking" and not self.thinking_visible:
                continue
            if role in {"tool-message", "tool-call", "tool"}:
                call_text = block.call_text
                if role == "tool-call":
                    call_text = call_text or Text(text, end="")
                is_bash = bool(call_text and call_text.plain.startswith("$ "))
                displayed_text = text if self.tools_expanded else ""
                output_lines = []
                collapsed_hint = False
                if not self.tools_expanded and is_bash and text:
                    all_lines = text.split("\n")
                    output_lines = [
                        Text(line, end="")
                        for line in all_lines[-_COLLAPSED_TOOL_PREVIEW_LINES:]
                    ]
                    hidden_lines = len(all_lines) - len(output_lines)
                    if hidden_lines:
                        hint = Text(end="")
                        hint.append(
                            f"... ({hidden_lines} earlier lines, ",
                            style=Style(color="#707070"),
                        )
                        hint.append(
                            "ctrl+o",
                            style=Style(color="#a0a0a0", bold=True),
                        )
                        hint.append(
                            " to expand)",
                            style=Style(color="#707070"),
                        )
                        output_lines.insert(
                            0,
                            hint,
                        )
                        collapsed_hint = True
                if displayed_text:
                    output_lines = (
                        _render_markdown_lines(displayed_text)
                        if role in {"tool-message", "tool"}
                        and self.render_tool_markdown
                        and self.tools_expanded
                        else [
                            Text(line, end="")
                            for line in displayed_text.split("\n")
                        ]
                    )
                if role == "tool-call":
                    output_lines = []
                block_lines = [Text("", end="")]
                if call_text:
                    block_lines.append(call_text.copy())
                block_lines.extend(output_lines)
                block_lines.append(Text("", end=""))
                block_roles = (
                    ["tool-message-padding"]
                    + (["tool-message-call"] if call_text else [])
                    + (["tool-message-hint"] if collapsed_hint else [])
                    + ["tool-message-output"]
                    * (len(output_lines) - int(collapsed_hint))
                    + ["tool-message-padding"]
                )
            else:
                if role == "system" and block.rich_text is not None:
                    block_lines = list(block.rich_text.split("\n")) or [Text(end="")]
                elif role in {"user", "system"}:
                    block_lines = [
                        Text(line, end="") for line in text.split("\n") or [""]
                    ]
                else:
                    block_lines = _render_markdown_lines(text)
                block_roles = [role] * len(block_lines)
            if role in {"user", "assistant"}:
                block_lines = (
                    [Text("", end="")] * self.user_top_blank_lines
                    + block_lines
                    + [Text("", end="")] * self.user_bottom_blank_lines
                )
                block_roles = (
                    [role] * self.user_top_blank_lines
                    + block_roles
                    + [role] * self.user_bottom_blank_lines
                )
            if has_rendered_block:
                styled_lines.append(Text("", end=""))
                line_roles.append("spacer")
            styled_lines.extend(block_lines)
            line_roles.extend(block_roles)
            has_rendered_block = True
        self._styled_lines = styled_lines
        self._line_roles = line_roles
        self.text = "\n".join(line.plain for line in styled_lines)
        self.display = bool(styled_lines)
        self.scroll_end(animate=False)

    def set_thinking_visible(self, visible: bool) -> None:
        self.thinking_visible = visible
        self._refresh_blocks()

    def set_tools_expanded(self, expanded: bool) -> None:
        self.tools_expanded = expanded
        self._refresh_blocks()

    def set_tool_markdown(self, enabled: bool) -> None:
        self.render_tool_markdown = enabled
        self._refresh_blocks()

    def clear_transcript(self) -> None:
        self.text = ""
        self._blocks = []
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
        elif role == "system":
            if not line.spans:
                line.stylize(Style(color=self.THINKING_FOREGROUND))
            if self.system_text_format != "normal":
                line.stylize(
                    Style(
                        bold=self.system_text_format == "bold",
                        italic=self.system_text_format == "italic",
                    )
                )
        elif role == "thinking":
            line.stylize(Style(color=self.THINKING_FOREGROUND, italic=True))
        elif role in {
            "tool-message-call",
            "tool-message-output",
            "tool-message-hint",
            "tool-message-padding",
        }:
            line.stylize(
                Style(
                    bgcolor=self.tool_message_background,
                )
            )
            if role == "tool-message-output":
                line.stylize(Style(color=self.tool_output_color))
            elif role == "tool-message-padding":
                line.stylize(Style(color=self.TOOL_FOREGROUND))
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
        strip = Strip(
            (
                Segment(segment.text, _as_rich_style(segment.style), segment.control)
                for segment in strip
            ),
            cell_length=strip.cell_length,
        )
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
        elif role in {
            "tool-message-call",
            "tool-message-output",
            "tool-message-hint",
            "tool-message-padding",
        }:
            role_style = Style(
                bgcolor=self.tool_message_background,
            )
        content_width = strip.cell_length
        for segment in reversed(list(strip)):
            if not segment.text:
                continue
            trimmed = segment.text.rstrip(" ")
            if trimmed:
                content_width -= segment.cell_length - len(trimmed)
                break
            content_width -= segment.cell_length
        content_width = max(0, content_width)
        content = strip.crop(0, content_width)
        if role_style is not None:
            content = Strip(
                Segment.apply_style(content, style=role_style),
                cell_length=content.cell_length,
            )
        selection_start, selection_end = sorted(self.selection)
        line_selected = (
            selection_start != selection_end
            and selection_start[0] <= line_index <= selection_end[0]
        )
        padded_roles = {
            "user",
            "assistant",
            "system",
            "thinking",
            "success",
            "tool-message-call",
            "tool-message-output",
            "tool-message-hint",
            "tool-message-padding",
        }
        if role in padded_roles and self.message_left_padding:
            padding = self.message_left_padding
            first_style = next(
                (segment.style for segment in content if segment.cell_length),
                None,
            )
            prefix = Strip(
                [Segment(" " * padding, first_style or role_style)],
                padding,
            )
            content = Strip.join([prefix, content])
        if content.cell_length < strip.cell_length:
            fill_style = (
                role_style
                if role
                in {
                    "user",
                    "tool-message-call",
                    "tool-message-output",
                    "tool-message-hint",
                    "tool-message-padding",
                }
                else Style(bgcolor=self.styles.background.rich_color)
            )
            strip = Strip.join(
                [
                    content,
                    Strip.blank(
                        strip.cell_length - content.cell_length,
                        fill_style,
                    ),
                ]
            )
        else:
            strip = content
        if line_selected:
            if not self.document[line_index]:
                strip = Strip.blank(
                    strip.cell_length,
                    Style(color="#000000", bgcolor="#ffffff"),
                )
            else:
                strip = Strip(
                    Segment.apply_style(
                        strip,
                        post_style=Style(color="#000000", bgcolor="#ffffff"),
                    ),
                    cell_length=strip.cell_length,
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
        cast(TextualPeonApp, self.app).query_one("#prompt", PeonInput).focus()
        event.stop()
        event.prevent_default()

    async def _on_mouse_up(self, event: MouseUp) -> None:
        await super()._on_mouse_up(event)
        cast(TextualPeonApp, self.app).query_one("#prompt", PeonInput).focus()

    def on_key(self, event: Key) -> None:
        app = cast(TextualPeonApp, self.app)
        if event.key == "escape":
            event.stop()
            event.prevent_default()
            app.action_clear_prompt()
        elif app.shortcut_matches(event.key, "thinking"):
            event.stop()
            event.prevent_default()
            app.action_toggle_thinking()
        elif app.shortcut_matches(event.key, "reasoning"):
            event.stop()
            event.prevent_default()
            app.action_cycle_reasoning()
        elif app.shortcut_matches(event.key, "tools"):
            event.stop()
            event.prevent_default()
            app.action_toggle_tools()
        elif event.character and event.character.isprintable():
            prompt = app.query_one("#prompt", PeonInput)
            prompt.focus()
            prompt.insert_text_at_cursor(event.character)
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
        padding: 0 1;
        color: $text-muted;
    }

    #choice-search {
        height: 1;
        display: none;
        border: none;
        padding: 0 1;
        background: $background;
        color: $text;
    }

    #choice-count {
        height: 1;
        display: none;
        padding: 0 1;
        color: $text-muted;
    }

    #choice-hint {
        height: 1;
        display: none;
        padding: 0 1;
        color: $text-muted;
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
        padding: 0 2;
    }

    #status-details {
        height: 1;
        background: $panel;
        padding: 0 2;
    }

    #status-context {
        width: 1fr;
        color: $text-muted;
    }

    #status-provider {
        width: 1fr;
        color: $text-muted;
        text-align: right;
    }

    #processing {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        display: none;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "clear_input", "", show=False, priority=True),
        Binding("escape", "clear_prompt", "", show=False, priority=True),
        ("ctrl+d", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        provider_factory: ProviderFactory | None,
        config_store: ProviderConfigStore,
        registry: ExtensionRegistry,
        session_store: SessionStore | None = None,
        continue_session: bool = False,
        no_session: bool = False,
        session_target: str | None = None,
        session_name: str | None = None,
        resources: ResourceInventory | None = None,
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
        self.session_store = session_store or MemorySessionStore()
        if no_session:
            self.session_store = MemorySessionStore()
        self.continue_session = continue_session
        self.session_target = session_target
        self.session_name = session_name
        self.resources = resources
        self.session_id = ""
        self.run_id = ""
        self.session_usage: Usage | None = None
        self.persisted_message_count = 0
        discovered_skill_names = (
            tuple(skill.name for skill in resources.skills)
            if resources is not None
            else discover_skill_names()
        )
        self.skill_names = tuple(
            dict.fromkeys((*registry.skills, *discovered_skill_names))
        )
        self.setup_step: SetupStep | None = None
        self.pending_config: ProviderConfig | None = None
        self.pending_setting_spec: ProviderSettingSpec | None = None
        self.pending_ui_setting: tuple[str, str, str | None] | None = None
        self.settings_return_kind: SetupStep | None = None
        self.pending_models: tuple[str, ...] = ()
        self.choice_values: list[object] = []
        self.choice_kind: SetupStep | None = None
        self.choice_all_values: list[object] = []
        self.choice_all_labels: list[str] = []
        self.choice_all_search_text: list[str] = []
        self.choice_labels: list[str] = []
        self.choice_query = ""
        self.choice_selected_index = 0
        self.choice_generation = 0
        self.choice_history: list[_ChoiceState] = []
        self._last_escape_at: float | None = None
        self.command_matches: tuple[CommandMatch, ...] = ()
        self.command_selected_index = 0
        self.quit_confirmation_active = False
        self.quit_confirmation_label = ""
        self.quit_confirmation_password = False
        self.quit_confirmation_value = ""
        self.tools_expanded = False
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
        self.task_worker: Worker[TurnResult | str] | None = None
        self.execution_context: ToolExecutionContext | None = None
        self.controller: SessionController | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="conversation"):
            yield ChatMessage(
                id="transcript",
                user_top_blank_lines=self.user_top_blank_lines,
                user_bottom_blank_lines=self.user_bottom_blank_lines,
                message_left_padding=self.message_left_padding,
                user_message_color=self.ui_config.user_message_color,
                user_message_background=self.ui_config.user_message_background,
                assistant_message_color=self.ui_config.assistant_message_color,
                tool_message_background=self.ui_config.tool_message_background,
                tool_output_color=self.ui_config.tool_output_color,
                render_tool_markdown=self.ui_config.render_tool_markdown,
                text_format=self.ui_config.text_format,
                system_text_format=self.ui_config.system_text_format,
            )
        yield ChoiceSearchInput(placeholder="> ", id="choice-search")
        yield Static("", id="setup-label")
        yield Static("", id="choices")
        yield Static("", id="choice-count")
        yield Static("", id="choice-hint")
        yield ProcessingStatus(self.processing_status_text, id="processing")
        with Vertical(id="composer"):
            yield Static("", id="suggestions")
            yield PeonInput(
                placeholder="Ask Peon or type / for commands",
                id="prompt",
            )
        yield Static("", id="status")
        with Horizontal(id="status-details"):
            yield Static("", id="status-context")
            yield Static("", id="status-provider")

    def on_mount(self) -> None:
        self.title = "Peon"
        self._apply_ui_config()
        self._restore_conversation()
        config = self.config_store.load()
        if config is not None:
            self._activate(config)
        else:
            self._begin_provider_setup()

    def _restore_conversation(self) -> None:
        latest: SessionRecord | None
        try:
            if self.session_target is not None:
                latest = select_session(self.session_store, self.session_target)
            else:
                latest = (
                    self.session_store.load_latest()
                    if self.continue_session
                    else None
                )
                if latest is None:
                    latest = create_session(
                        self.session_store,
                        name=self.session_name,
                    )
            self.session_id = latest.session_id
            self.context = AgentContext(messages=list(latest.messages))
            if self.resources is not None:
                apply_resource_prompt(self.context, self.resources)
            self.persisted_message_count = len(self.context.messages)
        except (OSError, SessionStoreError) as caught:
            self._write(f"Could not open saved session: {caught}")
            if self.session_target is not None:
                self.exit(1)
                return
            fallback = MemorySessionStore()
            latest = fallback.create(name=self.session_name)
            self.session_store = fallback
            self.session_id = latest.session_id
            self.context = AgentContext()
            if self.resources is not None:
                apply_resource_prompt(self.context, self.resources)
            self.persisted_message_count = len(self.context.messages)
        self._append_startup_message()
        for message in self.context.messages:
            self._append_context_message(message)

    def _append_startup_message(self) -> None:
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_message(_render_startup(self.resources), role="system")

    def _append_context_message(self, message: object) -> None:
        if not hasattr(message, "role"):
            return
        typed_message = cast(object, message)
        role = getattr(typed_message, "role")
        transcript = self.query_one("#transcript", ChatMessage)
        if role == "user":
            transcript.append_message(getattr(typed_message, "content"), role="user")
        elif role == "assistant":
            thinking = getattr(typed_message, "thinking", None)
            if thinking:
                transcript.append_message(thinking, role="thinking")
            tool_call = getattr(typed_message, "tool_call", None)
            if tool_call is not None:
                transcript.append_message(
                    _format_tool_call(tool_call),
                    role="tool-call",
                    tool_call_id=tool_call.call_id,
                )
            elif getattr(typed_message, "content"):
                transcript.append_message(
                    getattr(typed_message, "content"),
                    role="assistant",
                )
        elif role == "tool":
            transcript.append_message(
                getattr(typed_message, "content"),
                role="tool",
                tool_call_id=getattr(typed_message, "tool_call_id", None),
            )

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
        transcript.tool_message_background = self.ui_config.tool_message_background
        transcript.tool_output_color = self.ui_config.tool_output_color
        transcript.set_tool_markdown(self.ui_config.render_tool_markdown)
        transcript.text_format = self.ui_config.text_format
        transcript.system_text_format = self.ui_config.system_text_format
        transcript.set_thinking_visible(not self.ui_config.hide_thinking)
        transcript.set_tools_expanded(self.tools_expanded)
        transcript.refresh()

    def shortcut_matches(self, key: str, setting: str) -> bool:
        field_name = {
            "reasoning": "reasoning_shortcut",
            "thinking": "thinking_shortcut",
            "tools": "tools_shortcut",
        }[setting]
        return key.casefold() == str(getattr(self.ui_config, field_name)).casefold()

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.action_clear_prompt()
            event.stop()
            event.prevent_default()
            return
        if self.shortcut_matches(event.key, "thinking"):
            self.action_toggle_thinking()
            event.stop()
            event.prevent_default()
            return
        if self.shortcut_matches(event.key, "reasoning"):
            self.action_cycle_reasoning()
            event.stop()
            event.prevent_default()
            return
        if self.shortcut_matches(event.key, "tools"):
            self.action_toggle_tools()
            event.stop()
            event.prevent_default()
            return
        if event.key == "ctrl+c":
            self._handle_ctrl_c(event)
            return
        if self.choice_kind is not None and event.key in {"up", "down"}:
            self.move_choice_selection(1 if event.key == "down" else -1)
            event.stop()
            event.prevent_default()
            return
        if self.choice_kind is not None and event.key in {"enter", "space"}:
            self.select_current_choice()
            event.stop()
            event.prevent_default()
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
        self.action_clear_input()
        event.stop()
        event.prevent_default()

    def _is_non_input_focus(self) -> bool:
        return self.focused is not None and not isinstance(
            self.focused,
            (PeonInput, ChoiceSearchInput),
        )

    def select_choice_number(self, number: int) -> None:
        index = number - 1
        if self.choice_kind is not None and 0 <= index < len(self.choice_values):
            self._select_choice(index)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "choice-search":
            self.update_choice_search(event.value)

    def update_choice_search(self, value: str) -> None:
        if self.choice_kind is None:
            return
        selected_value = (
            self.choice_values[self.choice_selected_index]
            if 0 <= self.choice_selected_index < len(self.choice_values)
            else None
        )
        self.choice_query = value
        tokens = value.casefold().split()
        visible_indices = [
            index
            for index, search_text in enumerate(self.choice_all_search_text)
            if all(token in search_text for token in tokens)
        ]
        self.choice_values = [
            self.choice_all_values[index] for index in visible_indices
        ]
        self.choice_labels = [
            self.choice_all_labels[index] for index in visible_indices
        ]
        self.choice_selected_index = next(
            (
                index
                for index, choice in enumerate(self.choice_values)
                if choice == selected_value
            ),
            0,
        )
        self._render_choices()

    def update_command_suggestions(self, value: str) -> None:
        matches: tuple[CommandMatch, ...] = ()
        if value.startswith("/"):
            matches = self._command_matches(value)
            if not matches and any(character.isspace() for character in value):
                command_head = value.split(maxsplit=1)[0]
                matches = self._command_matches(command_head)
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
        start = self._visible_start(
            self.command_selected_index,
            len(self.command_matches),
        )
        visible_matches = self.command_matches[start : start + 6]
        for offset, match in enumerate(visible_matches):
            index = start + offset
            if offset:
                rendered.append("\n")
            selected = index == self.command_selected_index
            rendered.append("> " if selected else "  ", style="dim")
            command = match.command
            rendered.append(
                command.name,
                style=self._selected_command_style() if selected else "bold",
            )
            rendered.append(f"  {command.description}", style="dim")
            if command.candidate_names:
                rendered.append(
                    f"  (also: {', '.join(command.candidate_names)})",
                    style="dim italic",
                )
            if match.is_reserved:
                rendered.append("  [reserved]", style="yellow")
        if self.command_matches:
            rendered.append("\n")
            rendered.append(
                f"({self.command_selected_index + 1}/{len(self.command_matches)})",
                style="dim",
            )
            rendered.append("\n")
            rendered.append(
                "Up/Down navigate · Tab complete · Enter run · Esc close",
                style="dim",
            )
        self.query_one("#suggestions", Static).update(rendered)

    @staticmethod
    def _visible_start(selected: int, total: int, limit: int = 6) -> int:
        if total <= limit:
            return 0
        return min(max(0, selected - limit // 2), total - limit)

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

    def move_choice_selection(self, direction: int) -> None:
        if not self.choice_values:
            return
        self.choice_selected_index = (
            self.choice_selected_index + direction
        ) % len(self.choice_values)
        self._render_choices()

    def select_current_choice(self) -> None:
        if self.choice_values:
            self._select_choice(self.choice_selected_index)

    @staticmethod
    def _choice_label(label: str) -> str:
        stripped = label.strip()
        prefix, separator, remainder = stripped.partition(".")
        if separator and prefix.isdigit():
            return remainder.strip()
        return stripped

    @staticmethod
    def _choice_search_text(value: object, label: str) -> str:
        parts = [label, str(value)]
        if isinstance(value, ProviderSettingSpec):
            parts.extend((value.key, value.field_name, value.label))
        elif isinstance(value, tuple) and value and isinstance(value[0], str):
            parts.append(value[0])
        return " ".join(parts).casefold()

    def _render_choices(self) -> None:
        rendered = Text()
        start = self._visible_start(
            self.choice_selected_index,
            len(self.choice_values),
        )
        visible_labels = self.choice_labels[start : start + 6]
        for offset, label in enumerate(visible_labels):
            index = start + offset
            if offset:
                rendered.append("\n")
            selected = index == self.choice_selected_index
            rendered.append("> " if selected else "  ", style="dim")
            value = self.choice_values[index]
            if self.choice_kind == "session" and isinstance(value, SessionRecord):
                rendered.append(self._render_session_choice(value, selected))
            else:
                rendered.append(
                    label,
                    style=self._selected_command_style() if selected else "bold",
                )
        self.query_one("#choices", Static).update(rendered)
        count = (
            f"({self.choice_selected_index + 1}/{len(self.choice_values)})"
            if self.choice_values
            else "(0/0)"
        )
        self.query_one("#choice-count", Static).update(count)
        self.query_one("#choice-hint", Static).update(
            "Type to search · Enter/Space to change · Esc back · hold Esc close"
        )

    def _render_session_choice(
        self,
        session: SessionRecord,
        selected: bool,
    ) -> Text:
        title = " ".join((session_first_prompt(session) or "(no prompt)").split())
        metadata = format_session_metadata(
            session,
            delimiter=self.ui_config.session_list_delimiter,
        )
        choices = self.query_one("#choices", Static)
        width = choices.size.width
        if width <= 0:
            # Reserve the conversation and choices horizontal insets before
            # the first layout pass reports the widget width.
            width = max(1, self.size.width - 4)
        content_width = max(1, width - 2 - 2)
        title_width = max(1, content_width - len(metadata) - 1)
        if len(title) > title_width:
            title = (
                title[: max(0, title_width - 3)].rstrip() + "..."
                if title_width > 3
                else "." * title_width
            )
        gap = max(1, content_width - len(title) - len(metadata))
        row = Text(end="")
        row.append(
            title,
            style=self._selected_command_style() if selected else "bold",
        )
        row.append(" " * gap)
        row.append(
            metadata,
            style=self._selected_command_style() if selected else "dim",
        )
        return row

    def _selected_command_style(self) -> Style:
        return Style(
            color=self.ui_config.command_selected_color,
            bgcolor="#808080",
            bold=True,
        )

    def _command_matches(self, value: str) -> tuple[CommandMatch, ...]:
        normalized = value.strip().lstrip("/").casefold()
        matches = (
            []
            if normalized.startswith("skill:")
            else list(DEFAULT_COMMAND_CATALOG.search(value))
        )
        if not normalized or normalized.startswith("skill:") or normalized == "skill":
            skill_query = normalized.removeprefix("skill:").strip()
            for index, skill in enumerate(self.skill_names):
                if not skill_query or skill.casefold().startswith(skill_query):
                    command = CommandDefinition(
                        id=f"skill:{skill}",
                        name=f"/skill:{skill}",
                        description=(
                            "run registered skill"
                            if skill in self.registry.skills
                            else "skill available but not loaded"
                        ),
                        order=1000 + index,
                    )
                    matches.append(
                        CommandMatch(command, 2, "candidate-exact")
                    )
        return tuple(matches)

    def action_clear_prompt(self) -> None:
        if self.quit_confirmation_active:
            self._finish_quit_confirmation("")
            return
        if self.command_matches:
            self.dismiss_command_palette()
            self._last_escape_at = None
            return
        if self.choice_kind is not None or self.setup_step is not None:
            now = time.monotonic()
            repeated_escape = (
                self._last_escape_at is not None
                and _ESCAPE_REPEAT_DELAY
                <= now - self._last_escape_at
                < _ESCAPE_REPEAT_WINDOW
            )
            self._last_escape_at = now
            if repeated_escape:
                self._cancel_selection()
            elif not self._restore_previous_choice():
                return
            return
        self._last_escape_at = None
        if self.controller is not None and self.task_worker is not None:
            if self.controller.cancel():
                self._write("Task cancellation requested.", role="system")
                return
        if self.execution_context is not None and not self.execution_context.cancelled:
            self.execution_context.cancel()
            self._write("Task cancellation requested.", role="system")
            return
        self.query_one("#prompt", PeonInput).action_clear()

    def action_clear_input(self) -> None:
        if self.controller is not None and self.task_worker is not None:
            if self.controller.cancel():
                self._write("Task cancellation requested.", role="system")
                return
        if self.execution_context is not None and not self.execution_context.cancelled:
            self.execution_context.cancel()
            self._write("Task cancellation requested.", role="system")
            return
        self.dismiss_command_palette()
        self._last_escape_at = None
        self.query_one("#prompt", PeonInput).clear()

    def action_cycle_reasoning(self) -> None:
        if self.config is not None:
            self._cycle_active_reasoning()

    def action_toggle_thinking(self) -> None:
        self.ui_config = replace(
            self.ui_config,
            hide_thinking=not self.ui_config.hide_thinking,
        )
        try:
            save_ui_config(self.config_store, self.ui_config)
        except OSError as caught:
            self._write(f"Thinking setting could not be saved: {caught}")
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.set_thinking_visible(not self.ui_config.hide_thinking)
        self._write(
            "Thinking blocks: "
            + ("visible" if not self.ui_config.hide_thinking else "hidden"),
            role="success",
        )
        self._set_status()

    def action_toggle_tools(self) -> None:
        self.tools_expanded = not self.tools_expanded
        self.query_one("#transcript", ChatMessage).set_tools_expanded(
            self.tools_expanded
        )

    def _append_runtime_message(self, message: object) -> None:
        if hasattr(message, "role"):
            self.persisted_message_count = len(self.context.messages)
        if getattr(message, "role", None) == "user":
            return
        self._append_context_message(message)
        self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)

    def action_confirm_quit(self) -> None:
        if isinstance(self.focused, ChatMessage) and self.focused.selected_text:
            self.copy_to_clipboard(self.focused.selected_text)
            return
        if isinstance(self.focused, PeonInput):
            if self.focused.selected_text:
                self.copy_to_clipboard(self.focused.selected_text)
            else:
                self._begin_quit_confirmation()

    def _quit_with_resume(self) -> None:
        discarded = False
        if not any(message.role == "user" for message in self.context.messages):
            discarded = discard_empty_session(self.session_store, self.session_id)
        resume_command = self._resume_command()
        if resume_command is not None and not discarded:
            self._write(resume_command)
        self.exit(0)

    async def action_quit(self) -> None:
        self._quit_with_resume()

    def _write(self, text: str, *, role: str = "system") -> None:
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_message(text, role=role)
        conversation = self.query_one("#conversation", VerticalScroll)
        conversation.scroll_end(animate=False)

    def _set_processing(self, active: bool) -> None:
        self.query_one("#processing", ProcessingStatus).display = active
        prompt = self.query_one("#prompt", PeonInput)
        prompt.disabled = active
        if not active:
            prompt.focus()

    def _on_session_event(self, event: SessionEvent) -> None:
        if isinstance(event, MessageEvent):
            self.call_from_thread(
                self._append_runtime_message,
                event.message,
            )

    def _build_controller(self) -> None:
        assert self.provider is not None
        assert self.config is not None
        self.controller = SessionController(
            provider=self.provider,
            session_store=self.session_store,
            session_id=self.session_id,
            run_id=self.run_id or None,
            context=self.context,
            executor=filter_tool_executor(self.ui_config, self.registry),
            model=self.config.model,
            resources=self.resources,
            on_event=self._on_session_event,
            on_tool_output=lambda stream, chunk: self.call_from_thread(
                self._append_bash_output,
                None,
                stream,
                chunk,
            ),
        )
        self.run_id = self.controller.run_id

    def _run_task(self, task: str) -> TurnResult:
        assert self.controller is not None
        return self.controller.dispatch(PromptIntent(task))

    def _start_task(self, task: str) -> None:
        self._set_processing(True)
        self.execution_context = None
        self._build_controller()
        self.task_worker = cast(
            Worker[TurnResult | str],
            self.run_worker(
                lambda: self._run_task(task),
                name="peon-task",
                group="peon-task",
                exclusive=True,
                exit_on_error=False,
                thread=True,
            ),
        )

    def _start_shell_command(self, command: str, *, send_to_model: bool) -> None:
        if not command:
            self._write("bash command is required")
            return
        if not any(tool.name == "bash" for tool in self.registry.tools):
            self._write("bash tool is not registered")
            return
        call = ToolCall(
            name="bash",
            arguments={"command": command},
            call_id=f"shell-{time.monotonic_ns()}",
        )
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_message(
            _format_tool_call(call),
            role="tool-call",
            tool_call_id=call.call_id,
        )
        self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)
        self._set_processing(True)
        self.controller = None
        execution_context = ToolExecutionContext(
            on_output=lambda stream, chunk: self.call_from_thread(
                self._append_bash_output,
                execution_context,
                stream,
                chunk,
            )
        )
        self.execution_context = execution_context
        self.task_worker = cast(
            Worker[TurnResult | str],
            self.run_worker(
                lambda: self._run_shell_command(
                    command,
                    send_to_model=send_to_model,
                    execution_context=execution_context,
                    call_id=call.call_id or "",
                ),
                name="peon-bash",
                group="peon-task",
                exclusive=True,
                exit_on_error=False,
                thread=True,
            ),
        )

    def _run_shell_command(
        self,
        command: str,
        *,
        send_to_model: bool,
        execution_context: ToolExecutionContext,
        call_id: str,
    ) -> str | TurnResult:
        result = self.registry.invoke_with_context(
            "bash",
            {"command": command},
            execution_context,
        )
        self.call_from_thread(self._append_shell_result, result, call_id)
        if not send_to_model:
            return result
        self._build_controller()
        return self._run_task(
            f"Shell command `{command}` output:\n{result}"
        )

    def _append_shell_result(self, result: str, call_id: str) -> None:
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_message(
            result,
            role="tool",
            tool_call_id=call_id,
        )
        self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)

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
            if isinstance(result, TurnResult):
                self.session_usage = merge_usage(self.session_usage, result.usage)
                if result.status == "cancelled":
                    self._write("Task cancelled.", role="system")
                elif result.status == "error":
                    self._write(result.error or "task failed", role="system")
            elif isinstance(result, ToolCall):
                self._write(
                    f"provider requested unhandled tool '{result.name}'",
                    role="system",
                )
        elif event.state == WorkerState.ERROR:
            error = event.worker.error
            if self.execution_context is not None and self.execution_context.cancelled:
                self._write("Task cancelled.", role="system")
            else:
                self._write(str(error or "task failed"), role="system")
        self.task_worker = None
        self.execution_context = None
        self._set_processing(False)
        self._set_status()

    def _append_bash_output(
        self,
        execution_context: ToolExecutionContext | None,
        stream: str,
        chunk: str,
    ) -> None:
        if (
            execution_context is not None
            and self.execution_context is not execution_context
        ):
            return
        del stream
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.append_tool_output(chunk)
        self.query_one("#conversation", VerticalScroll).scroll_end(animate=False)

    def _set_status(self) -> None:
        if self.config is None:
            context_status = "setup required"
            provider_status = ""
        else:
            context_status = (
                f"context {len(self.context.messages)}  ·  "
                f"effort {self.config.reasoning_effort or 'none'}  ·  tokens n/a"
            )
            provider_status = (
                f"{self.config.name}  ·  {self.config.model or 'no model'}"
            )
        self.query_one("#status", Static).update(str(Path.cwd()))
        self.query_one("#status-context", Static).update(context_status)
        self.query_one("#status-provider", Static).update(provider_status)

    def _show_choices(
        self,
        kind: SetupStep,
        title: str,
        choices: list[tuple[object, str]],
    ) -> None:
        if self.choice_history:
            latest = self.choice_history[-1]
            if latest.kind == kind and latest.title == title:
                self.choice_history.pop()
        self.setup_step = kind
        self.choice_kind = kind
        self.choice_values = [value for value, _label in choices]
        self.choice_all_values = list(self.choice_values)
        self.choice_all_labels = [
            self._choice_label(label) for _value, label in choices
        ]
        self.choice_all_search_text = [
            self._choice_search_text(value, label)
            for (value, label) in choices
        ]
        self.choice_labels = list(self.choice_all_labels)
        self.choice_query = ""
        self.choice_selected_index = 0
        self.choice_generation += 1
        self.query_one("#setup-label", Static).update(title)
        search = self.query_one("#choice-search", ChoiceSearchInput)
        search.value = ""
        search.display = True
        self.query_one("#choices", Static).display = True
        self.query_one("#choice-count", Static).display = True
        self.query_one("#choice-hint", Static).display = True
        self._render_choices()
        search.focus()

    def _choice_state(self) -> _ChoiceState | None:
        if self.choice_kind is None:
            return None
        return _ChoiceState(
            kind=self.choice_kind,
            title=str(self.query_one("#setup-label", Static).renderable),
            all_values=list(self.choice_all_values),
            all_labels=list(self.choice_all_labels),
            all_search_text=list(self.choice_all_search_text),
            values=list(self.choice_values),
            labels=list(self.choice_labels),
            query=self.choice_query,
            selected_index=self.choice_selected_index,
        )

    def _remember_choice(self) -> None:
        state = self._choice_state()
        if state is not None:
            self.choice_history.append(state)

    def _restore_previous_choice(self) -> bool:
        if not self.choice_history:
            return False
        state = self.choice_history.pop()
        self.setup_step = state.kind
        self.choice_kind = state.kind
        self.choice_all_values = list(state.all_values)
        self.choice_all_labels = list(state.all_labels)
        self.choice_all_search_text = list(state.all_search_text)
        self.choice_values = list(state.values)
        self.choice_labels = list(state.labels)
        self.choice_query = state.query
        self.choice_selected_index = state.selected_index
        self.choice_generation += 1
        self.query_one("#setup-label", Static).update(state.title)
        search = self.query_one("#choice-search", ChoiceSearchInput)
        search.value = state.query
        search.display = True
        self.query_one("#choices", Static).display = True
        self.query_one("#choice-count", Static).display = True
        self.query_one("#choice-hint", Static).display = True
        self._render_choices()
        search.focus()
        return True

    def _hide_choices(self) -> None:
        self.query_one("#choice-search", ChoiceSearchInput).display = False
        self.query_one("#choices", Static).display = False
        self.query_one("#choice-count", Static).display = False
        self.query_one("#choice-hint", Static).display = False
        self.query_one("#setup-label", Static).update("")
        self.choice_values = []
        self.choice_all_values = []
        self.choice_all_labels = []
        self.choice_all_search_text = []
        self.choice_labels = []
        self.choice_query = ""
        self.choice_selected_index = 0
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

    def _select_choice(self, index: int) -> None:
        value = self.choice_values[index]
        kind = self.choice_kind
        should_remember = kind in {
            "provider",
            "settings-root",
            "settings-provider-type",
            "settings-provider",
            "settings-profile",
        }
        if kind in {"settings-config", "settings-request", "settings-response"}:
            should_remember = cast(ProviderSettingSpec, value).value_kind not in {
                "toggle",
                "choice",
            }
        elif kind == "settings-ui":
            should_remember = cast(tuple[str, str, str], value)[2] != "text_format"
        if should_remember:
            self._remember_choice()
        self._hide_choices()
        if kind == "provider":
            self._start_provider_inputs(str(value))
        elif kind == "saved-provider":
            self._activate(value)  # type: ignore[arg-type]
        elif kind == "session":
            self._open_selected_session(cast(SessionRecord, value))
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
        elif kind == "settings-general":
            self._select_general_setting(cast(tuple[str, str, str | None], value))
        elif kind == "settings-shortcuts":
            self._select_shortcut_setting(cast(tuple[str, str, str], value))
        elif kind == "settings-tools":
            self._select_tool_setting(str(value))
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
                ("general", "4. General"),
                ("shortcuts", "5. Shortcuts"),
                ("tools", "6. Tool availability"),
            ],
        )

    def _select_settings_root(self, section: str) -> None:
        if section == "ui":
            self._show_ui_settings()
        elif section == "add-provider":
            self._begin_provider_setup()
        elif section == "general":
            self._show_general_settings()
        elif section == "shortcuts":
            self._show_shortcut_settings()
        elif section == "tools":
            self._show_tool_settings()
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
            config = self.pending_config or self.config
            return provider_config_setting_specs(config) if config else ()
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
            self.choice_selected_index = focused_index
            self._render_choices()

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
            self.choice_selected_index = focused_index
            self._render_choices()

    def _show_general_settings(self, *, focus_key: str | None = None) -> None:
        self._show_choices(
            "settings-general",
            "General settings:",
            [
                (
                    spec,
                    f"{index}. {label:<28} "
                    + (
                        "[reserved]"
                        if field_name is None
                        else _format_setting_value(getattr(self.ui_config, field_name))
                    ),
                )
                for index, spec in enumerate(GENERAL_SETTING_SPECS, 1)
                for _key, label, field_name in (spec,)
            ],
        )
        if focus_key is not None:
            self.choice_selected_index = next(
                (
                    index
                    for index, spec in enumerate(GENERAL_SETTING_SPECS)
                    if spec[0] == focus_key
                ),
                0,
            )
            self._render_choices()

    def _show_shortcut_settings(self, *, focus_key: str | None = None) -> None:
        self._show_choices(
            "settings-shortcuts",
            "Shortcut settings:",
            [
                (
                    spec,
                    f"{index}. {label:<28} {getattr(self.ui_config, field_name)}",
                )
                for index, spec in enumerate(SHORTCUT_SETTING_SPECS, 1)
                for _key, label, field_name in (spec,)
            ],
        )
        if focus_key is not None:
            self.choice_selected_index = next(
                (
                    index
                    for index, spec in enumerate(SHORTCUT_SETTING_SPECS)
                    if spec[0] == focus_key
                ),
                0,
            )
            self._render_choices()

    def _show_tool_settings(self, *, focus_name: str | None = None) -> None:
        tool_names = tuple(
            dict.fromkeys(
                (
                    *self.ui_config.enabled_tools,
                    *(tool.name for tool in self.registry.tools),
                )
            )
        )
        enabled = set(self.ui_config.enabled_tools)
        self._show_choices(
            "settings-tools",
            "Tool availability:",
            [
                (
                    name,
                    f"{index}. {name:<24} {'true' if name in enabled else 'false'}",
                )
                for index, name in enumerate(tool_names, 1)
            ],
        )
        if focus_name is not None:
            self.choice_selected_index = next(
                (index for index, name in enumerate(tool_names) if name == focus_name),
                0,
            )
            self._render_choices()

    def _select_tool_setting(self, tool_name: str) -> None:
        enabled = tool_name in self.ui_config.enabled_tools
        try:
            self.ui_config = update_tool_setting(
                self.ui_config,
                tool_name,
                str(not enabled).lower(),
            )
            save_ui_config(self.config_store, self.ui_config)
        except (OSError, ValueError) as caught:
            self._write(f"Tool setting update failed: {caught}")
        self._show_tool_settings(focus_name=tool_name)

    def _session_label(self, session: SessionRecord) -> str:
        name = f" · {session.name}" if session.name else ""
        return (
            f"{format_session_summary(session, delimiter=self.ui_config.session_list_delimiter)}"
            f"{name}"
        )

    def _show_session_info(self) -> None:
        try:
            record = self.session_store.load(self.session_id)
        except (OSError, SessionStoreError) as caught:
            self._write(f"Could not inspect session: {caught}")
            return
        messages = tuple(
            conversation_messages_without_resource_prompt(
                self.context.messages,
                self.resources,
            )
        )
        record = replace(record, messages=messages)
        self._write(
            "\n".join(
                format_session_info(
                    record,
                    store=self.session_store,
                    usage=self.session_usage,
                )
            )
        )

    def _show_session_picker(self, argument: str) -> None:
        if argument:
            try:
                selected = select_session(self.session_store, argument)
            except SessionStoreError as caught:
                self._write(f"Could not open saved session: {caught}")
                return
            self._open_selected_session(selected)
            return
        try:
            sessions = tuple(
                session
                for session in self.session_store.list_sessions()
                if session_interaction_count(session) > 0
                and session.session_id != self.session_id
            )
        except (OSError, SessionStoreError) as caught:
            self._write(f"Could not list saved sessions: {caught}")
            return
        if not sessions:
            self._write("No saved sessions.")
            return
        self._show_choices(
            "session",
            "Select session:",
            [
                (session, f"{index}. {self._session_label(session)}")
                for index, session in enumerate(sessions, 1)
            ],
        )

    def _open_selected_session(self, selected: SessionRecord) -> None:
        if (
            selected.session_id != self.session_id
            and not any(message.role == "user" for message in self.context.messages)
        ):
            discard_empty_session(self.session_store, self.session_id)
        self.session_id = selected.session_id
        self.session_usage = None
        self.context = AgentContext(messages=list(selected.messages))
        if self.resources is not None:
            apply_resource_prompt(self.context, self.resources)
        self.persisted_message_count = len(self.context.messages)
        transcript = self.query_one("#transcript", ChatMessage)
        transcript.clear_transcript()
        self._append_startup_message()
        for message in self.context.messages:
            self._append_context_message(message)
        self._write(f"Resumed session: {self._session_label(selected)}")
        self._set_status()

    def _fork_current_session(self, name: str) -> None:
        messages = tuple(
            conversation_messages_without_resource_prompt(
                self.context.messages,
                self.resources,
            )
        )
        try:
            created = create_session(
                self.session_store,
                parent_id=self.session_id,
                name=name or None,
            )
            for message in messages:
                self.session_store.append(created.session_id, message)
        except (OSError, SessionStoreError) as caught:
            self._write(f"Could not fork conversation: {caught}")
            return
        self.session_id = created.session_id
        self.session_usage = None
        self.context = AgentContext(messages=list(messages))
        if self.resources is not None:
            apply_resource_prompt(self.context, self.resources)
        self.persisted_message_count = len(self.context.messages)
        self._write(f"Forked conversation: {self.session_id}")
        self._set_status()

    def _resume_command(self) -> str | None:
        if not isinstance(self.session_store, JsonlSessionStore):
            return None
        return f"Resume with: peon --session {self.session_id}"

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

    def _select_general_setting(
        self,
        spec: tuple[str, str, str | None],
    ) -> None:
        key, _label, field_name = spec
        if field_name is None:
            self._write(f"/{key} is reserved and is not available yet.")
            self._show_general_settings(focus_key=key)
            return
        current = getattr(self.ui_config, field_name)
        self._apply_general_setting(key, str(not bool(current)).lower())

    def _select_shortcut_setting(self, spec: tuple[str, str, str]) -> None:
        self.pending_setting_spec = None
        self.pending_ui_setting = spec
        self.settings_return_kind = "settings-shortcuts"
        self.setup_step = "setting-value"
        self._show_input_prompt(f"{spec[1]}:")

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

    def _apply_general_setting(self, setting: str, value: str) -> None:
        try:
            self.ui_config = update_general_setting(self.ui_config, setting, value)
            save_ui_config(self.config_store, self.ui_config)
        except (OSError, ValueError) as caught:
            self._write(f"General setting update failed: {caught}")
        self._apply_ui_config()
        self._show_general_settings(focus_key=setting)

    def _apply_shortcut_setting(self, setting: str, value: str) -> None:
        try:
            self.ui_config = update_shortcut_setting(self.ui_config, setting, value)
            save_ui_config(self.config_store, self.ui_config)
        except (OSError, ValueError) as caught:
            self._write(f"Shortcut update failed: {caught}")
        self._show_shortcut_settings(focus_key=setting)

    def _adjust_selected_setting(self, direction: int) -> bool:
        kind = self.choice_kind
        if kind not in {
            "settings-config",
            "settings-request",
            "settings-response",
            "settings-ui",
            "settings-general",
        }:
            return False
        index = self.choice_selected_index
        if not 0 <= index < len(self.choice_values):
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
        if kind == "settings-general":
            general_key, _label, general_field_name = cast(
                tuple[str, str, str | None],
                self.choice_values[index],
            )
            if general_field_name is None:
                return False
            general_current = getattr(self.ui_config, general_field_name)
            self._apply_general_setting(
                general_key,
                str(not bool(general_current)).lower(),
            )
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
        if value.startswith("!"):
            event.input.value = ""
            self.dismiss_command_palette()
            hidden = value.startswith("!!")
            command = value[2:] if hidden else value[1:]
            self._start_shell_command(
                command.strip(),
                send_to_model=not hidden,
            )
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
                if self.settings_return_kind == "settings-shortcuts":
                    self._apply_shortcut_setting(self.pending_ui_setting[0], value)
                elif self.settings_return_kind == "settings-general":
                    self._apply_general_setting(self.pending_ui_setting[0], value)
                else:
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
        self.choice_history = []
        self._last_escape_at = None
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
        normalized_name = name.casefold()
        if normalized_name.startswith("/skill:") and normalized_name != "/skill:":
            skill_name = name.split(":", maxsplit=1)[1]
            resource = (
                self.resources.find_skill(skill_name)
                if self.resources is not None
                else None
            )
            if resource is not None:
                load_skill_into_context(self.context, resource)
                self._write(
                    f"Skill '{resource.name}' ({resource.path}):\n{resource.content}"
                )
            elif skill_name in self.registry.skills:
                self._write(f"Skill '{skill_name}' is registered.")
            elif skill_name in self.skill_names:
                self._write(f"Skill '{skill_name}' is available but not loaded.")
            else:
                self._write(f"Unknown skill: {skill_name}")
            return
        invocation = DEFAULT_COMMAND_CATALOG.resolve(command)
        if invocation is None:
            self._write(f"Unknown command: {name}")
            return
        definition = invocation.command
        if definition.id.startswith("skill:"):
            skill_name = definition.id.removeprefix("skill:")
            if skill_name in self.registry.skills:
                self._write(f"Skill '{skill_name}' is registered.")
            elif skill_name in self.skill_names:
                self._write(f"Skill '{skill_name}' is available but not loaded.")
            else:
                self._write(f"Unknown skill: {skill_name}")
            return
        if definition.setting_key is not None:
            self._handle_provider_setting_command(
                definition.setting_key,
                invocation.argument,
            )
        elif definition.availability == "reserved":
            self._write(f"{definition.name} is reserved and is not available yet.")
        elif definition.id == "quit":
            self._quit_with_resume()
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
        elif definition.id == "session":
            self._show_session_info()
        elif definition.id == "resume":
            self._show_session_picker(invocation.argument)
        elif definition.id == "fork":
            self._fork_current_session(invocation.argument)
        elif definition.id == "new":
            if not any(message.role == "user" for message in self.context.messages):
                discard_empty_session(self.session_store, self.session_id)
            try:
                created = create_session(
                    self.session_store,
                    parent_id=self.session_id,
                )
            except (OSError, SessionStoreError) as caught:
                self._write(f"Could not start a new conversation: {caught}")
                return
            self.session_id = created.session_id
            self.session_usage = None
            self.context = AgentContext()
            if self.resources is not None:
                apply_resource_prompt(self.context, self.resources)
            self.persisted_message_count = len(self.context.messages)
            self.query_one("#transcript", ChatMessage).clear_transcript()
            self._append_startup_message()
            self._write("✓ New session started", role="success")
            self._set_status()
        elif definition.id == "tools":
            enabled = set(self.ui_config.enabled_tools)
            self._write(
                "Tools: "
                + ", ".join(
                    f"{tool.name} ({'enabled' if tool.name in enabled else 'disabled'})"
                    for tool in self.registry.tools
                )
            )
        elif definition.id == "skills":
            skills = self.skill_names
            self._write("Skills: " + ", ".join(skills) if skills else "Skills: none")

    def _handle_provider_setting_command(self, setting: str, value: str) -> None:
        if self.config is None:
            self._write("No active provider.")
            return
        if setting == "reasoning" and not reasoning_effort_choices(self.config):
            self._write("Reasoning effort is not supported by this provider.")
            return
        spec = (
            ProviderSettingSpec("name", "Name", "name", "text")
            if setting == "name"
            else next(
                spec
                for spec in provider_config_setting_specs(self.config)
                if spec.key == setting
            )
        )
        self.pending_config = self.config
        current = getattr(self.config, spec.field_name)
        if not value and spec.value_kind == "toggle":
            value = str(not bool(current)).lower()
        elif not value and setting == "reasoning":
            self._cycle_active_reasoning()
            return
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

    def _cycle_active_reasoning(self) -> None:
        if self.config is None:
            return
        if not reasoning_effort_choices(self.config):
            self._write("Reasoning effort is not supported by this provider.")
            return
        try:
            value = cycle_reasoning_effort(self.config)
            config = update_provider_setting(self.config, "reasoning", value)
            provider = (self.provider_factory or create_provider)(config)
            update_saved_provider(self.config_store, self.config, config)
        except (CommandError, ProviderError, OSError, ValueError) as caught:
            self._write(f"Reasoning update failed: {caught}")
            return
        self.pending_config = config
        self.provider = provider
        self.config = config
        self._set_status()

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
    session_store: SessionStore | None = None,
    continue_session: bool = False,
    no_session: bool = False,
    session_target: str | None = None,
    session_name: str | None = None,
    resources: ResourceInventory | None = None,
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
        session_store=session_store,
        continue_session=continue_session,
        no_session=no_session,
        session_target=session_target,
        session_name=session_name,
        resources=resources,
    )
    app.run()
    return int(app.return_code or 0)
