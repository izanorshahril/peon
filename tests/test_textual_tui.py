import asyncio
import threading

from rich.color import Color
from peon.agent import AgentMessage, ModelResponse
from peon.app import ProviderConfig
from peon.app.sessions import MemorySessionStore
from peon.app.textual_tui import ChatMessage, TextualPeonApp
from peon.extensions import ExtensionRegistry
from textual.document._document import Selection
from textual.events import MouseDown
from textual.widgets import Input, Static


class FakeProvider:
    def complete(self, *, messages, tools=(), model=None):
        return ModelResponse(content="ok")


class BlockingProvider(FakeProvider):
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def complete(self, *, messages, tools=(), model=None):
        self.started.set()
        self.release.wait(timeout=2)
        return ModelResponse(content="done")


class MemoryConfigStore:
    def __init__(self, configurations: tuple[ProviderConfig, ...]) -> None:
        self.configurations = list(configurations)

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


def provider_factory(config: ProviderConfig) -> FakeProvider:
    return FakeProvider()


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
            assert message.text == "\ncopy this text\n"
            assert message._line_roles == ["user", "user", "user"]
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
            assert str(app.query_one("#choice-count").renderable) == "(1/10)"
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
            assert not transcript.text
            assert not transcript.display

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
            message.selection = Selection((0, 0), (2, len("copy by right click")))
            await pilot.pause()
            await pilot._post_mouse_events(
                [MouseDown],
                widget=message,
                button=3,
            )
            assert copied == ["\ncopy by right click\n"]

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
            transcript.selection = Selection((0, 3), (1, 4))
            await pilot.pause()
            assert transcript.selection == Selection((0, 0), (1, len("hello user")))
            assert transcript.selected_text == "hello peon\nhello user"

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
            assert transcript.text == "\nHello\n\nbold and code\n"
            assert transcript._styled_lines[1].plain == "Hello"
            assert transcript._styled_lines[1].spans
            assert transcript._styled_lines[3].spans

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
            rendered = transcript.render_line(4)
            assert "response one" in "".join(segment.text for segment in rendered)

    asyncio.run(exercise())


def test_textual_user_background_fills_the_rendered_row() -> None:
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
            rendered = transcript.render_line(2)
            non_empty_segments = [segment for segment in rendered if segment.cell_length]
            assert rendered.cell_length == transcript.size.width
            assert all(
                segment.style is not None
                and segment.style.bgcolor is not None
                and segment.style.bgcolor == Color.parse(ChatMessage.USER_BACKGROUND)
                for segment in non_empty_segments
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
            assert transcript.text == "✓ New session started"
            assert transcript._line_roles == ["success"]
            assert transcript._styled_lines[0].plain == "✓ New session started"
            rendered = transcript.render_line(0)
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
            assert transcript.text == "\n\nhello\n\n\n\n\nanswer\n\n"
            assert transcript._line_roles == [
                "user",
                "user",
                "user",
                "user",
                "user",
                "assistant",
                "assistant",
                "assistant",
                "assistant",
                "assistant",
            ]
            assert transcript.render_line(2).text.startswith("   ")
            assert transcript.render_line(7).text.startswith("   ")
            assert all(
                segment.style is not None
                and segment.style.bgcolor
                == transcript.styles.background.rich_color
                for segment in transcript.render_line(5)
                if segment.cell_length
            )
            assert all(
                segment.style is not None
                and segment.style.bgcolor
                == transcript.styles.background.rich_color
                for segment in transcript.render_line(7)
                if segment.cell_length
            )

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
            startup = app.query_one("#startup", Static)
            assert startup.renderable.spans[0].start == 0
            assert startup.renderable.spans[0].end == len("peon")
            conversation = app.query_one("#conversation")
            transcript = app.query_one("#transcript", ChatMessage)
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

        async with TextualPeonApp(
            provider_factory=provider_factory,
            config_store=config_store,
            registry=ExtensionRegistry(),
            session_store=session_store,
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


def test_textual_ctrl_c_confirms_before_exit_and_restores_draft() -> None:
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
            prompt = app.query_one("#prompt")
            prompt.value = "unfinished question"
            await pilot.press("ctrl+c")
            assert str(app.query_one("#setup-label", Static).renderable) == "Exit Peon? [y/N]"
            assert prompt.value == ""
            prompt.value = "n"
            await pilot.press("enter")
            assert prompt.value == "unfinished question"
            assert str(app.query_one("#setup-label", Static).renderable) == ""
            await pilot.press("ctrl+c")
            prompt.value = "yes"
            await pilot.press("enter")

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
            assert "beta" in str(app.query_one("#status", Static).renderable)
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
