import asyncio
import threading
from pathlib import Path

from rich.color import Color
from rich.console import Console
from peon.agent import AgentMessage, ModelResponse, ToolCall
from peon.app import ProviderConfig, UiConfig
from peon.app.sessions import JsonlSessionStore, MemorySessionStore
from peon.app.resources import ContextResource, ResourceInventory, SkillResource
from peon.app.textual_tui import (
    ChatMessage,
    PeonInput,
    TextualPeonApp,
    _format_tool_call,
)
from peon.extensions import ExtensionRegistry
from textual.document._document import Selection
from textual.events import MouseDown
from textual.geometry import Region
from textual.widgets import Input, Static


class FakeProvider:
    def complete(self, *, messages, tools=(), model=None):
        return ModelResponse(content="ok")


class ShellProvider(FakeProvider):
    def __init__(self) -> None:
        self.received_messages = []

    def complete(self, *, messages, tools=(), model=None):
        self.received_messages.append(tuple(messages))
        return ModelResponse(content="shell result received")


class BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, *, messages, tools=(), model=None):
        self.started.set()
        self.release.wait(timeout=2)
        return ModelResponse(content="done")


class ToolProvider(FakeProvider):
    def __init__(self) -> None:
        self.responses = [
            ModelResponse(
                thinking="I should inspect the workspace first.",
                tool_call=ToolCall(
                    name="lookup",
                    arguments={"detail": "full", "key": "owner"},
                    call_id="call-1",
                ),
            ),
            ModelResponse(content="The owner is Peon."),
        ]

    def complete(self, *, messages, tools=(), model=None):
        return self.responses.pop(0)


class MemoryConfigStore:
    def __init__(self, configurations: tuple[ProviderConfig, ...]) -> None:
        self.configurations = list(configurations)
        self.ui_configuration = UiConfig()

    def load(self) -> ProviderConfig | None:
        return self.configurations[-1] if self.configurations else None

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return tuple(self.configurations)

    def save(self, config: ProviderConfig) -> None:
        for index, existing in enumerate(self.configurations):
            if existing.name == config.name and existing.base_url == config.base_url:
                self.configurations[index] = config
                return
        self.configurations.append(config)

    def delete(self, config: ProviderConfig) -> None:
        self.configurations = [
            existing
            for existing in self.configurations
            if existing != config
        ]

    def load_ui(self) -> UiConfig:
        return self.ui_configuration

    def save_ui(self, config: UiConfig) -> None:
        self.ui_configuration = config


def provider_factory(config: ProviderConfig) -> FakeProvider:
    return FakeProvider()


def test_textual_startup_styles_sections_and_spaces_context() -> None:
    config = ProviderConfig(
        name="openai-compatible",
        model="alpha",
        base_url="https://example.test/v1",
    )
    resources = ResourceInventory(
        skills=(
            SkillResource(
                name="notes",
                description="Notes",
                content="Use notes.",
                path=Path("notes/SKILL.md"),
                base_directory=Path("notes"),
                source="project",
            ),
        ),
        context_files=(
            ContextResource(
                path=Path("AGENTS.md"),
                content="Rules",
                source="project",
            ),
        ),
        effective_system_prompt="prompt",
    )
    app = TextualPeonApp(
        provider_factory=provider_factory,
        config_store=MemoryConfigStore((config,)),
        registry=ExtensionRegistry(),
        resources=resources,
    )

    async def exercise() -> None:
        async with app.run_test():
            transcript = app.query_one("#transcript", ChatMessage)
            assert "peon v0.2.0" in transcript.text
            assert "\n\n[Context]" in transcript.text
            assert "[Skills]\n  notes" in transcript.text
            assert "#startup" not in {widget.id for widget in app.query("Static")}
            peon_line = transcript.get_line(0)
            assert any(
                span.style is not None
                and str(span.style) == "#8bd5ff"
                for span in peon_line.spans
            )
            context_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if line.plain == "[Context]"
            )
            context_line = transcript.get_line(context_index)
            assert any(
                span.style is not None
                and str(span.style) == "#f2c94c"
                for span in context_line.spans
            )

            transcript.selection = Selection((0, 0), (0, len(peon_line)))
            startup_rows = [
                transcript.render_line(row)
                for row in range(transcript.size.height)
                if "peon v0.2.0" in "".join(
                    segment.text for segment in transcript.render_line(row)
                )
            ]
            assert any(
                segment.style is not None
                and segment.style.color == Color.parse("#000000")
                and segment.style.bgcolor == Color.parse("#ffffff")
                for row in startup_rows
                for segment in row
            )

            transcript.append_message("later output", role="assistant")
            assert transcript.text.index("peon v0.2.0") < transcript.text.index(
                "later output"
            )

    asyncio.run(exercise())


def test_textual_ctrl_c_clears_prompt_from_app_binding() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", PeonInput)
            prompt.focus()
            prompt.value = "draft"
            await pilot.press("ctrl+c")
            assert prompt.value == ""
            assert not app.quit_confirmation_active

    asyncio.run(exercise())


def test_textual_bang_command_sends_shell_output_to_model() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        provider = ShellProvider()
        registry = ExtensionRegistry()

        def bash(arguments, context=None):
            assert arguments["command"] == "echo hello"
            if context is not None and context.on_output is not None:
                context.on_output("stdout", "hello\n")
            return "bash: exit code 0\nstatus: exited\nstdout:\nhello"

        registry.register_tool(
            name="bash",
            description="Run commands",
            parameters={"type": "object"},
            handler=bash,
        )
        app = TextualPeonApp(
            provider_factory=lambda _config: provider,
            config_store=MemoryConfigStore((config,)),
            registry=registry,
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", PeonInput)
            prompt.value = "!echo hello"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not app.query_one("#processing").display:
                    break
            transcript = app.query_one("#transcript", ChatMessage)
            assert "$ echo hello" in transcript.text
            assert "shell result received" in transcript.text
            assert any(
                "Shell command `echo hello` output:" in message.content
                for messages in provider.received_messages
                for message in messages
                if message.role == "user"
            )

    asyncio.run(exercise())


def test_textual_hidden_bang_command_does_not_call_model() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        provider = ShellProvider()
        registry = ExtensionRegistry()
        registry.register_tool(
            name="bash",
            description="Run commands",
            parameters={"type": "object"},
            handler=lambda arguments: "hello",
        )
        app = TextualPeonApp(
            provider_factory=lambda _config: provider,
            config_store=MemoryConfigStore((config,)),
            registry=registry,
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", PeonInput)
            prompt.value = "!!echo hello"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not app.query_one("#processing").display:
                    break
            assert provider.received_messages == []

    asyncio.run(exercise())


def test_textual_mounts_stable_layout_and_command_suggestions() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            models=("alpha", "beta"),
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            conversation = app.query_one("#conversation")
            assert app.query_one("#composer")
            assert app.query_one("#status")
            app._write("copy this text", role="user")
            message = app.query_one("#transcript", ChatMessage)
            assert message.read_only
            assert message.text.endswith("\ncopy this text\n")
            assert message._line_roles[-3:] == ["user", "user", "user"]
            assert conversation.styles.align_vertical == "bottom"
            prompt = app.query_one("#prompt")
            prompt.value = "/mo"
            await pilot.pause()
            suggestions = app.query_one("#suggestions", Static)
            assert str(suggestions.renderable).startswith("> /model")
            assert "/models" not in str(suggestions.renderable)
            await pilot.press("tab")
            assert prompt.value == "/model"
            assert app.focused is prompt
            prompt.value = "/mo"
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#choices").display
            await pilot.press("escape")
            await pilot.pause(0.4)
            await pilot.press("escape")
            prompt.value = "/mo"
            message.focus()
            await pilot.press("x")
            assert prompt.value == "/mox"
            assert app.focused is prompt
            prompt.value = "/quit"
            await pilot.press("enter")

    asyncio.run(exercise())


def test_textual_command_palette_wraps_selection_and_preserves_draft_on_escape() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/"
            await pilot.pause()
            assert "(also: reset)" in str(app.query_one("#suggestions").renderable)
            assert f"(1/{len(app.command_matches)})" in str(
                app.query_one("#suggestions").renderable
            )
            assert app.command_selected_index == 0

            await pilot.press("up")
            assert app.command_selected_index == len(app.command_matches) - 1
            await pilot.press("down")
            assert app.command_selected_index == 0

            prompt.value = "/mo"
            await pilot.press("escape")
            assert prompt.value == "/mo"
            assert not app.command_matches
            assert str(app.query_one("#suggestions").renderable) == ""

    asyncio.run(exercise())


def test_textual_picker_search_and_focus_loss_keep_selection_safe() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "1")
            await pilot.pause()

            assert app.choice_kind == "settings-ui"
            assert str(app.query_one("#choice-count").renderable) == "(1/13)"
            assert "Type to search" in str(app.query_one("#choice-hint").renderable)
            assert str(app.query_one("#choices").renderable).startswith("> User top spacing")

            search = app.query_one("#choice-search", Input)
            search.focus()
            await pilot.press("a")
            assert search.value == "a"
            search.value = ""
            search.value = "assistant"
            await pilot.pause()
            assert str(app.query_one("#choice-count").renderable) == "(1/1)"
            assert "Assistant message color" in str(app.query_one("#choices").renderable)

            prompt.focus()
            await pilot.press("down")
            assert app.choice_selected_index == 0
            assert app.ui_config.assistant_message_color == "#e0e0e0"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind is None

    asyncio.run(exercise())


def test_textual_escape_backtracks_when_picker_has_lost_focus() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "1")
            await pilot.pause()
            assert app.choice_kind == "settings-ui"

            prompt.focus()
            await pilot.press("escape")
            assert app.choice_kind == "settings-root"

    asyncio.run(exercise())


def test_textual_shortcuts_toggle_thinking_and_cycle_reasoning_separately() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
            reasoning_effort="low",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            await pilot.press("ctrl+t")
            assert app.ui_config.hide_thinking
            await pilot.press("shift+tab", "shift+tab", "shift+tab")
            assert app.config is not None
            assert app.config.reasoning_effort is None
            assert "effort none" in str(
                app.query_one("#status-context", Static).renderable
            )

    asyncio.run(exercise())


def test_textual_thinking_toggle_refreshes_visible_blocks() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            app._write("private reasoning", role="thinking")
            transcript = app.query_one("#transcript", ChatMessage)
            assert "private reasoning" in transcript.text

            await pilot.press("ctrl+t")
            assert not transcript.thinking_visible
            assert "private reasoning" not in transcript.text
            assert "Thinking blocks: hidden" in transcript.text

            await pilot.press("ctrl+t")
            assert transcript.thinking_visible
            assert "private reasoning" in transcript.text
            assert "Thinking blocks: visible" in transcript.text

    asyncio.run(exercise())


def test_textual_general_settings_toggle_thinking() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "4")
            await pilot.pause()
            assert app.choice_kind == "settings-general"
            await pilot.press("enter")
            assert app.ui_config.hide_thinking

    asyncio.run(exercise())


def test_textual_renders_tool_blocks_and_collapses_output() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        registry = ExtensionRegistry()
        registry.register_tool(
            name="lookup",
            description="Look up a value.",
            parameters={"type": "object"},
            handler=lambda arguments: f"**value:{arguments['key']}**",
        )
        app = TextualPeonApp(
            provider_factory=lambda _config: ToolProvider(),
            config_store=MemoryConfigStore((config,)),
            registry=registry,
        )
        app.ui_config = UiConfig(enabled_tools=("lookup",))

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt")
            prompt.value = "inspect"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not app.query_one("#processing").display:
                    break
            transcript = app.query_one("#transcript", ChatMessage)
            assert "I should inspect the workspace first." in transcript.text
            assert 'lookup: key="owner"' in transcript.text
            assert "Tool call:" not in transcript.text
            assert "lookup({" not in transcript.text
            assert "\n\n" in transcript.text
            assert "[tool output collapsed]" not in transcript.text
            assert "**value:owner**" not in transcript.text
            assert "The owner is Peon." in transcript.text
            assert "detail" not in transcript.text
            assert transcript._line_roles.count("tool-message-call") == 1
            assert transcript._line_roles.count("tool-message-output") == 0
            assert transcript._line_roles.count("tool-message-padding") == 2
            await pilot.press("ctrl+t")
            assert "I should inspect the workspace first." not in transcript.text
            await pilot.press("ctrl+t")
            assert "I should inspect the workspace first." in transcript.text
            await pilot.press("ctrl+o")
            assert "**value:owner**" in transcript.text

            app.ui_config = UiConfig(
                enabled_tools=("lookup",),
                render_tool_markdown=True,
                tool_message_background="#282832",
            )
            app._apply_ui_config()
            assert transcript.tool_message_background == "#282832"
            assert "value:owner" in transcript.text
            assert "**value:owner**" not in transcript.text

            tool_rows = []
            for y in range(transcript.size.height):
                document_offset = y + transcript.scroll_offset.y
                if document_offset >= transcript.wrapped_document.height:
                    continue
                line_info = transcript.wrapped_document._offset_to_line_info[
                    document_offset
                ]
                if line_info is None:
                    continue
                line_index, _section_offset = line_info
                if transcript._line_roles[line_index] == "tool-message-call":
                    tool_rows.append(transcript.render_line(y))
            assert tool_rows
            assert all(
                segment.style is not None
                and segment.style.bgcolor
                == Color.parse(transcript.tool_message_background)
                for row in tool_rows
                for segment in row
                if segment.cell_length
            )

    asyncio.run(exercise())


def test_textual_tool_call_has_semantic_path_and_parameter_styles() -> None:
    rendered = _format_tool_call(
        ToolCall(
            name="read",
            arguments={"path": "src/main.py", "offset": 3, "limit": 2},
            call_id="call-1",
        )
    )

    assert rendered.plain == "read src/main.py limit=2 offset=3"
    segments = list(rendered.render(Console()))
    path_segments = [
        segment
        for segment in segments
        if segment.text == "src/main.py"
    ]
    assert path_segments
    assert path_segments[0].style is not None
    assert path_segments[0].style.link is not None
    assert path_segments[0].style.color is not None
    assert any(segment.text == "limit=2" for segment in segments)
    assert any(segment.text == "offset=3" for segment in segments)


def test_textual_message_background_and_padding_fill_role_rows() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
            user_top_blank_lines=0,
            user_bottom_blank_lines=0,
            message_left_padding=2,
        )

        async with app.run_test(size=(40, 20)) as pilot:
            app._write("hello", role="user")
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage)
            user_row = next(
                row
                for row in range(transcript.size.height)
                if "hello" in "".join(
                    segment.text for segment in transcript.render_line(row)
                )
            )
            row = transcript.render_line(user_row)
            background = Color.parse(transcript.user_message_background)
            colored_cells = sum(
                segment.cell_length
                for segment in row
                if segment.style is not None and segment.style.bgcolor == background
            )
            assert colored_cells == transcript.size.width
            assert "".join(segment.text for segment in row).startswith("  hello")

            transcript.focus()
            prompt = app.query_one("#prompt")
            await pilot.press("x")
            assert app.focused is prompt
            assert prompt.value == "x"

    asyncio.run(exercise())


def test_textual_restarts_with_a_separate_jsonl_store_and_restores_blocks(tmp_path) -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        registry = ExtensionRegistry()
        registry.register_tool(
            name="lookup",
            description="Look up a value.",
            parameters={"type": "object"},
            handler=lambda arguments: f"value:{arguments['key']}",
        )
        first_app = TextualPeonApp(
            provider_factory=lambda _config: ToolProvider(),
            config_store=MemoryConfigStore((config,)),
            registry=registry,
            session_store=JsonlSessionStore(tmp_path / "sessions"),
        )
        first_app.ui_config = UiConfig(enabled_tools=("lookup",))

        async with first_app.run_test() as pilot:
            prompt = first_app.query_one("#prompt")
            prompt.value = "inspect"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not first_app.query_one("#processing").display:
                    break
            assert len(first_app.context.messages) == 4

        second_app = TextualPeonApp(
            provider_factory=lambda _config: ToolProvider(),
            config_store=MemoryConfigStore((config,)),
            registry=registry,
            session_store=JsonlSessionStore(tmp_path / "sessions"),
            continue_session=True,
        )
        second_app.ui_config = UiConfig(enabled_tools=("lookup",))

        async with second_app.run_test():
            assert len(second_app.context.messages) == 4
            transcript = second_app.query_one("#transcript", ChatMessage)
            assert 'lookup: key="owner"' in transcript.text
            assert "[tool output collapsed]" not in transcript.text
            assert "value:owner" not in transcript.text
            assert "The owner is Peon." in transcript.text

    asyncio.run(exercise())


def test_textual_skills_command_lists_registered_skills() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        registry = ExtensionRegistry()
        registry.register_skill("notes", lambda target: None)
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=registry,
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/skill:n"
            await pilot.pause()
            assert "/skill:notes" in str(app.query_one("#suggestions").renderable)
            await pilot.press("enter")
            await pilot.pause()
            assert "Skill 'notes' is registered." in app.query_one("#transcript").text

            prompt.value = "/skills"
            await pilot.press("enter")
            await pilot.pause()
            assert "Skills: notes" in str(app.query_one("#transcript").text)

    asyncio.run(exercise())


def test_textual_selected_command_preserves_typed_argument() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            models=("alpha", "beta"),
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/mo 2"
            await pilot.press("enter")
            await pilot.pause()
            assert app.config is not None
            assert app.config.model == "beta"

    asyncio.run(exercise())


def test_textual_number_selects_focused_choice_instead_of_prompt() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/provider"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "provider"
            await pilot.press("3")
            await pilot.pause()

            assert app.pending_config is not None
            assert app.pending_config.provider_type == "custom"
            assert prompt.value == ""
            assert app.focused is prompt

    asyncio.run(exercise())


def test_textual_changes_custom_provider_setting() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
        config_store = MemoryConfigStore((config,))
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "settings-root"
            await pilot.press("2", "1", "1", "3", "1")
            await pilot.pause()
            prompt.value = "reasoning_effort"
            await pilot.press("enter")
            await pilot.pause()

            assert app.config is not None
            assert app.config.reasoning_effort_field == "reasoning_effort"
            assert config_store.load() == app.config
            assert app.choice_kind == "settings-request"

    asyncio.run(exercise())


def test_textual_adjusts_ui_and_provider_config_without_closing_lists() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "1", "right")
            await pilot.pause()
            assert app.ui_config.user_top_blank_lines == 2
            assert app.choice_kind == "settings-ui"

            await pilot.press("escape")
            await pilot.pause(0.4)
            await pilot.press("escape")
            prompt.value = "/settings"
            await pilot.press("enter", "2", "1", "1", "2")
            await pilot.pause()
            assert app.choice_kind == "settings-config"
            await pilot.press("down", "down", "down", "down", "down", "right")
            await pilot.pause()
            assert app.config is not None
            assert app.config.reasoning_effort == "medium"
            assert app.choice_kind == "settings-config"
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.config.supports_tools is True
            assert app.choice_kind == "settings-config"

    asyncio.run(exercise())


def test_textual_changes_provider_config_with_slash_commands() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/temperature 0.3"
            await pilot.press("enter")
            prompt.value = "/reasoning high"
            await pilot.press("enter")
            prompt.value = "/supports-chat-completions"
            await pilot.press("enter")
            await pilot.pause()
            assert app.config is not None
            assert app.config.temperature == 0.3
            assert app.config.reasoning_effort == "high"
            assert app.config.supports_chat_completions is False

    asyncio.run(exercise())


def test_textual_empty_transcript_uses_screen_background() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage)
            assert "peon v0.2.0" in transcript.text
            assert transcript.display

    asyncio.run(exercise())


def test_textual_right_click_copies_message_text() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )
        copied: list[str] = []

        async with app.run_test() as pilot:
            app.copy_to_clipboard = copied.append
            app._write("copy by right click", role="assistant")
            await pilot.pause()
            message = app.query_one("#transcript", ChatMessage)
            message_index = next(
                index
                for index, line in enumerate(message._styled_lines)
                if "copy by right click" in line.plain
            )
            message.selection = Selection(
                (message_index, 0),
                (message_index, len("copy by right click")),
            )
            await pilot.pause()
            await pilot._post_mouse_events(
                [MouseDown],
                widget=message,
                button=3,
            )
            assert copied == ["copy by right click"]
            assert app.focused is app.query_one("#prompt")
            await pilot.press("x")
            assert app.query_one("#prompt").value == "x"

    asyncio.run(exercise())


def test_textual_prompt_selection_is_visible_and_right_click_copies() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )
        copied: list[str] = []

        async with app.run_test() as pilot:
            app.copy_to_clipboard = copied.append
            prompt = app.query_one("#prompt", PeonInput)
            prompt.value = "copy from prompt"
            prompt.select_range(5, 9)
            rendered = prompt._value
            assert any(
                span.style == prompt.get_component_rich_style("input--selection")
                for span in rendered.spans
            )
            await pilot._post_mouse_events(
                [MouseDown],
                widget=prompt,
                button=3,
            )
            assert copied == ["from"]

    asyncio.run(exercise())


def test_textual_selection_spans_messages_and_snaps_to_lines() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
            user_top_blank_lines=0,
            user_bottom_blank_lines=0,
        )

        async with app.run_test() as pilot:
            app._write("hello peon", role="user")
            app._write("hello user", role="assistant")
            transcript = app.query_one("#transcript", ChatMessage)
            user_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if line.plain == "hello peon"
            )
            assistant_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if line.plain == "hello user"
            )
            transcript.selection = Selection(
                (user_index, 3),
                (assistant_index, 4),
            )
            await pilot.pause()
            assert transcript.selection == Selection(
                (user_index, 0),
                (assistant_index, len("hello user")),
            )
            assert transcript.selected_text == "hello peon\n\nhello user"
            selected_rows = [
                transcript.render_line(row)
                for row in range(transcript.size.height)
                if "hello peon" in "".join(
                    segment.text for segment in transcript.render_line(row)
                )
            ]
            assert selected_rows
            assert all(
                segment.style is not None
                and segment.style.color == Color.parse("#000000")
                and segment.style.bgcolor == Color.parse("#ffffff")
                for row in selected_rows
                for segment in row
                if segment.cell_length
            )

    asyncio.run(exercise())


def test_textual_renders_assistant_markdown() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            app._write("# Hello\n\n**bold** and `code`", role="assistant")
            transcript = app.query_one("#transcript", ChatMessage)
            await pilot.pause()
            assert transcript.text.endswith("\nHello\n\nbold and code\n")
            hello_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if line.plain == "Hello"
            )
            code_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if line.plain == "bold and code"
            )
            assert transcript._styled_lines[hello_index].spans
            assert transcript._styled_lines[code_index].spans

    asyncio.run(exercise())


def test_textual_renders_response_immediately_after_user_message() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            app._write("hello one", role="user")
            app._write("response one", role="assistant")
            transcript = app.query_one("#transcript", ChatMessage)
            await pilot.pause()
            response_index = next(
                index
                for index, line in enumerate(transcript._styled_lines)
                if "response one" in line.plain
            )
            rendered = transcript.render_line(response_index)
            assert "response one" in "".join(segment.text for segment in rendered)

    asyncio.run(exercise())


def test_textual_user_background_fills_message_row() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(100, 30)) as pilot:
            app._write("first user", role="user")
            app._write("assistant response", role="assistant")
            app._write("second user", role="user")
            transcript = app.query_one("#transcript", ChatMessage)
            await pilot.pause()
            background = Color.parse(transcript.user_message_background)
            user_rows = []
            for y in range(transcript.size.height):
                document_offset = y + transcript.scroll_offset.y
                if document_offset >= transcript.wrapped_document.height:
                    continue
                line_info = transcript.wrapped_document._offset_to_line_info[
                    document_offset
                ]
                if line_info is None:
                    continue
                line_index, _section_offset = line_info
                if line_index >= len(transcript._line_roles):
                    continue
                if transcript._line_roles[line_index] == "user":
                    user_rows.append(transcript.render_line(y))
            assert user_rows
            assert all(row.cell_length == transcript.size.width for row in user_rows)
            assert all(
                sum(
                    segment.cell_length
                    for segment in row
                    if segment.style is not None
                    and segment.style.bgcolor == background
                )
                == transcript.size.width
                for row in user_rows
            )

    asyncio.run(exercise())


def test_textual_assistant_background_matches_transcript_at_narrow_width() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(45, 20)) as pilot:
            app._write("hello", role="user")
            app._write("Hello! How can I help you today?", role="assistant")
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage)
            expected_background = transcript.styles.background.rich_color
            assistant_rows = 0

            for y in range(transcript.size.height):
                document_offset = y + transcript.scroll_offset.y
                if document_offset >= transcript.wrapped_document.height:
                    continue
                line_info = transcript.wrapped_document._offset_to_line_info[
                    document_offset
                ]
                if line_info is None:
                    continue
                line_index, _section_offset = line_info
                if transcript._line_roles[line_index] != "assistant":
                    continue
                assistant_rows += 1
                rendered = transcript.render_line(y)
                assert rendered.cell_length == transcript.size.width
                assert all(
                    "\n" not in segment.text and "\r" not in segment.text
                    for segment in rendered
                )
                backgrounds = [
                    segment.style.bgcolor
                    for segment in rendered
                    if segment.cell_length and segment.style is not None
                ]
                assert backgrounds
                assert all(
                    background == expected_background for background in backgrounds
                )

            assert assistant_rows == 3

    asyncio.run(exercise())


def test_textual_render_lines_accepts_chat_message_segment_styles() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(100, 30)) as pilot:
            app._write("render this user message", role="user")
            app._write("render this assistant message", role="assistant")
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage)
            strips = transcript.render_lines(
                Region(0, 0, transcript.size.width, transcript.size.height)
            )
            assert len(strips) == transcript.size.height

    asyncio.run(exercise())


def test_textual_clear_shows_new_session_success_message() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            app._write("old response", role="assistant")
            prompt = app.query_one("#prompt")
            prompt.value = "/clear"
            await pilot.press("enter")
            transcript = app.query_one("#transcript", ChatMessage)
            assert "peon v0.2.0" in transcript.text
            assert transcript.text.endswith("✓ New session started")
            success_index = transcript._line_roles.index("success")
            assert transcript._styled_lines[success_index].plain == (
                "✓ New session started"
            )
            rendered = transcript.render_line(success_index)
            assert any(
                segment.style is not None
                and segment.style.color == Color.parse(ChatMessage.SUCCESS_FOREGROUND)
                for segment in rendered
                if segment.cell_length
            )

    asyncio.run(exercise())


def test_textual_user_blocks_have_configurable_spacing_and_left_inset() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
            user_top_blank_lines=2,
            user_bottom_blank_lines=2,
            message_left_padding=3,
        )

        async with app.run_test(size=(100, 30)) as pilot:
            app._write("hello", role="user")
            app._write("answer", role="assistant")
            transcript = app.query_one("#transcript", ChatMessage)
            await pilot.pause()
            assert transcript.styles.background == app.screen.styles.background
            assert transcript.text.endswith("\n\nhello\n\n\n\n\n\nanswer\n\n")
            hello_row = next(
                row
                for row in range(transcript.size.height)
                if "hello" in "".join(
                    segment.text for segment in transcript.render_line(row)
                )
            )
            answer_row = next(
                row
                for row in range(transcript.size.height)
                if "answer" in "".join(
                    segment.text for segment in transcript.render_line(row)
                )
            )
            assert transcript.render_line(hello_row).text.startswith("   ")
            assert transcript.render_line(answer_row).text.startswith("   ")
            background = transcript.styles.background.rich_color
            assert any(
                not "".join(
                    segment.text for segment in transcript.render_line(row)
                ).strip()
                and all(
                    segment.style is not None
                    and segment.style.bgcolor == background
                    for segment in transcript.render_line(row)
                    if segment.cell_length
                )
                for row in range(hello_row + 1, answer_row)
            )
            assert all(
                segment.style is not None
                and segment.style.bgcolor
                == transcript.styles.background.rich_color
                for segment in transcript.render_line(answer_row)
                if segment.cell_length
            )

    asyncio.run(exercise())


def test_textual_collapsed_tool_output_shows_tail_preview_and_hint() -> None:
    transcript = ChatMessage(
        user_top_blank_lines=0,
        user_bottom_blank_lines=0,
    )
    transcript.append_message(
        _format_tool_call(
            ToolCall(
                name="bash",
                arguments={"command": "pytest", "timeout": 10},
                call_id="call-1",
            )
        ),
        role="tool-call",
        tool_call_id="call-1",
    )
    transcript.append_message(
        "one\ntwo\nthree\nfour\nfive\nsix",
        role="tool",
        tool_call_id="call-1",
    )

    assert "one" not in transcript.text
    assert "two\nthree\nfour\nfive\nsix" in transcript.text
    assert "... (1 earlier lines, ctrl+o to expand)" in transcript.text
    hint_index = transcript.text.splitlines().index(
        "... (1 earlier lines, ctrl+o to expand)"
    )
    assert transcript._line_roles[hint_index] == "tool-message-hint"


def test_textual_footer_has_cwd_and_split_context_provider_rows() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
            reasoning_effort="high",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(100, 30)):
            cwd = str(app.query_one("#status", Static).renderable)
            context = str(app.query_one("#status-context", Static).renderable)
            provider = str(app.query_one("#status-provider", Static).renderable)
            assert cwd == str(Path.cwd())
            assert "context 0" in context
            assert "effort high" in context
            assert "openai-compatible" in provider
            assert "alpha" in provider

    asyncio.run(exercise())


def test_textual_header_color_and_bottom_anchor() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test(size=(100, 30)) as pilot:
            app._write("first output", role="assistant")
            await pilot.pause()
            conversation = app.query_one("#conversation")
            transcript = app.query_one("#transcript", ChatMessage)
            assert "peon v0.2.0" in transcript.text
            assert "first output" in transcript.text
            assert not app.query("#startup")
            assert conversation.styles.align_vertical == "bottom"
            assert transcript.region.bottom == conversation.region.bottom - 1

    asyncio.run(exercise())


def test_textual_typing_from_scroll_pane_returns_to_prompt() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            app._write("a response", role="assistant")
            app.query_one("#conversation").focus()
            await pilot.press("x")
            prompt = app.query_one("#prompt", Input)
            assert prompt.value == "x"
            assert app.focused is prompt

    asyncio.run(exercise())


def test_textual_processing_status_runs_while_provider_is_busy() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        provider = BlockingProvider()
        app = TextualPeonApp(
            provider_factory=lambda _config: provider,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt")
            prompt.value = "hello"
            await pilot.press("enter")
            await pilot.pause()
            assert provider.started.wait(timeout=1)
            processing = app.query_one("#processing")
            assert processing.display
            assert "Work...work!" in str(processing.renderable)
            provider.release.set()
            for _ in range(20):
                await pilot.pause()
                if not processing.display:
                    break
            assert not processing.display
            assert app.query_one("#transcript", ChatMessage).text.endswith("done\n")

    asyncio.run(exercise())


def test_textual_resumes_persistent_session() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        config_store = MemoryConfigStore((config,))
        session_store = MemorySessionStore()
        previous = session_store.create()
        session_store.append(
            previous.session_id,
            AgentMessage(role="user", content="old task"),
        )

        async with TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
            session_store=session_store,
        ).run_test() as pilot:
            prompt = pilot.app.query_one("#prompt")
            prompt.value = "hello"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if not pilot.app.query_one("#processing").display:
                    break
            assert pilot.app.query_one("#transcript", ChatMessage).text.endswith(
                "ok\n"
            )
            assert pilot.app.context.messages == [
                AgentMessage(role="user", content="hello"),
                AgentMessage(role="assistant", content="ok"),
            ]

        async with TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
            session_store=session_store,
            continue_session=True,
        ).run_test() as pilot:
            await pilot.pause()
            assert pilot.app.context.messages == [
                AgentMessage(role="user", content="hello"),
                AgentMessage(role="assistant", content="ok"),
            ]
            assert pilot.app.query_one("#transcript", ChatMessage).text.endswith(
                "ok\n"
            )

    asyncio.run(exercise())


def test_textual_session_picker_opens_named_session_and_fork_records_parent() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        config_store = MemoryConfigStore((config,))
        session_store = MemorySessionStore()
        source = session_store.create(name="source")
        session_store.append(
            source.session_id,
            AgentMessage(role="user", content="old task"),
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
            session_store=session_store,
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/resume"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "session"
            assert any("old task" in label for label in app.choice_all_labels)
            assert any(" · 1 · " in label for label in app.choice_all_labels)
            await pilot.press("down", "enter")
            assert app.session_id == source.session_id
            assert app.context.messages == [
                AgentMessage(role="user", content="old task")
            ]

            prompt.value = "/session"
            await pilot.press("enter")
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage)
            assert "Session Info" in transcript.text
            assert f"ID: {source.session_id}" in transcript.text
            assert "Messages" in transcript.text
            assert "Total: 1" in transcript.text
            assert "User: 1" in transcript.text
            assert "Tools: 0 calls, 0 results" in transcript.text

            prompt.value = "/fork branch"
            await pilot.press("enter")
            children = [
                session
                for session in session_store.list_sessions()
                if session.parent_id == source.session_id
            ]
            assert len(children) == 1
            assert children[0].parent_id == source.session_id
            assert children[0].name == "branch"
            assert session_store.load(source.session_id).messages == (
                AgentMessage(role="user", content="old task")
            ,)

    asyncio.run(exercise())


def test_textual_session_rows_truncate_prompt_and_align_metadata() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        config_store = MemoryConfigStore((config,))
        config_store.save_ui(UiConfig(session_list_delimiter=False))
        session_store = MemorySessionStore()
        source = session_store.create(name="source")
        session_store.append(
            source.session_id,
            AgentMessage(
                role="user",
                content=(
                    "This is a deliberately long first prompt that should be "
                    "truncated to the available terminal width"
                ),
            ),
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
            session_store=session_store,
        )

        async with app.run_test(size=(48, 20)) as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/resume"
            await pilot.press("enter")
            await pilot.pause()
            rendered = str(app.query_one("#choices", Static).renderable)
            assert "..." in rendered
            assert "1 now" in rendered
            assert " · " not in rendered

    asyncio.run(exercise())


def test_textual_quit_displays_resume_command_for_durable_session(tmp_path) -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
            session_store=JsonlSessionStore(tmp_path / "sessions"),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/quit"
            await pilot.press("enter")
            transcript = app.query_one("#transcript", ChatMessage)
            assert "peon v0.2.0" in transcript.text
            assert app.session_store.list_sessions() == ()

    asyncio.run(exercise())


def test_textual_tool_settings_enable_registered_tool() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        config_store = MemoryConfigStore((config,))
        registry = ExtensionRegistry()
        registry.register_tool(
            name="word_count",
            description="Count words.",
            parameters={"type": "object"},
            handler=lambda _arguments: "count",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=registry,
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "6")
            await pilot.pause()
            assert app.choice_kind == "settings-tools"
            assert "word_count" in str(app.query_one("#choices").renderable)
            await pilot.press("down", "down", "down", "down", "enter")
            assert "word_count" in app.ui_config.enabled_tools

    asyncio.run(exercise())


def test_textual_escape_cancels_model_and_provider_selection() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            models=("alpha", "beta"),
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt")
            prompt.value = "/model"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "model"
            await pilot.press("escape")
            await pilot.pause(0.4)
            await pilot.press("escape")
            assert app.choice_kind is None
            assert app.setup_step is None
            assert app.config == config
            assert app.focused is prompt

            prompt.value = "/provider"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "provider"
            await pilot.press("escape")
            await pilot.pause(0.4)
            await pilot.press("escape")
            assert app.choice_kind is None
            assert app.setup_step is None
            assert app.config == config
            assert app.focused is prompt

    asyncio.run(exercise())


def test_textual_escape_backtracks_nested_settings_and_long_escape_closes() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", Input)
            prompt.value = "/settings"
            await pilot.press("enter", "2", "1", "1", "2")
            await pilot.pause()
            assert app.choice_kind == "settings-config"

            for expected in (
                "settings-profile",
                "settings-provider",
                "settings-provider-type",
                "settings-root",
            ):
                await pilot.press("escape")
                await pilot.pause(0.8)
                assert app.choice_kind == expected

            await pilot.press("escape")
            assert app.choice_kind == "settings-root"
            await pilot.press("escape")
            await pilot.pause(0.4)
            await pilot.press("escape")
            assert app.choice_kind is None
            assert app.setup_step is None

    asyncio.run(exercise())


def test_textual_ctrl_c_clears_prompt_without_quit_confirmation() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt", PeonInput)
            prompt.value = "unfinished question"
            await pilot.press("ctrl+c")
            assert prompt.value == ""
            assert not app.quit_confirmation_active

    asyncio.run(exercise())


def test_textual_model_switch_updates_status_without_transcript_trace() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            models=("alpha", "beta"),
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=MemoryConfigStore((config,)),
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            prompt = app.query_one("#prompt")
            prompt.value = "/model beta"
            await pilot.press("enter")
            await pilot.pause()
            assert app.config is not None
            assert app.config.model == "beta"
            assert "beta" in str(
                app.query_one("#status-provider", Static).renderable
            )
            assert all(
                "Using provider" not in message.text
                for message in app.query("#conversation ChatMessage")
            )

    asyncio.run(exercise())


def test_textual_reuses_active_saved_provider_and_logs_out_selected_profile() -> None:
    async def exercise() -> None:
        first = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://first.example/v1",
        )
        second = ProviderConfig(
            name="openai-compatible",
            model="beta",
            base_url="https://second.example/v1",
        )
        store = MemoryConfigStore((first, second))
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=store,
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.config == second
            prompt = app.query_one("#prompt")
            prompt.value = "/logout"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down", "enter")
            await pilot.pause()
            assert store.load_all() == (first,)
            assert app.config == first

    asyncio.run(exercise())


def test_textual_logs_out_inactive_profile_without_switching_provider() -> None:
    async def exercise() -> None:
        first = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://first.example/v1",
        )
        second = ProviderConfig(
            name="openai-compatible",
            model="beta",
            base_url="https://second.example/v1",
        )
        store = MemoryConfigStore((first, second))
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=store,
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.config == second
            prompt = app.query_one("#prompt")
            prompt.value = "/logout"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert store.load_all() == (second,)
            assert app.config == second

    asyncio.run(exercise())


def test_textual_model_picker_aggregates_profiles_and_preserves_context() -> None:
    async def exercise() -> None:
        first = ProviderConfig(
            name="first provider",
            model="alpha",
            models=("alpha",),
            base_url="https://first.example/v1",
        )
        second = ProviderConfig(
            name="second provider",
            model="beta",
            models=("beta",),
            base_url="https://second.example/v1",
        )
        store = MemoryConfigStore((first, second))
        app = TextualPeonApp(
            provider_factory=provider_factory,
            config_store=store,
            registry=ExtensionRegistry(),
        )

        async with app.run_test() as pilot:
            context = app.context
            context.messages.append(AgentMessage(role="user", content="prior"))
            prompt = app.query_one("#prompt")
            prompt.value = "/models"
            await pilot.press("enter")
            await pilot.pause()
            transcript = app.query_one("#transcript", ChatMessage).text
            assert "alpha [first provider]" in transcript
            assert "beta [second provider]" in transcript
            prompt.value = "/model 1"
            await pilot.press("enter")
            await pilot.pause()
            assert app.config == first
            assert app.context is context
            assert context.messages == [AgentMessage(role="user", content="prior")]

    asyncio.run(exercise())
