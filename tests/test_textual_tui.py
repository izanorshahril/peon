import asyncio
import threading

from rich.color import Color
from peon.agent import ModelResponse
from peon.app import ProviderConfig
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
            assert "/models" in str(suggestions.renderable)
            await pilot.press("tab")
            assert prompt.value == "/model"
            assert app.focused is prompt
            prompt.value = "/mo"
            await pilot.press("enter")
            await pilot.pause()
            assert app.query_one("#choices").display
            await pilot.press("escape")
            prompt.value = "/mo"
            message.focus()
            await pilot.press("x")
            assert prompt.value == "/mox"
            assert app.focused is prompt
            prompt.value = "/quit"
            await pilot.press("enter")

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
            assert app.choice_kind is None
            assert app.setup_step is None
            assert app.config == config
            assert app.focused is prompt

            prompt.value = "/provider"
            await pilot.press("enter")
            await pilot.pause()
            assert app.choice_kind == "provider"
            await pilot.press("escape")
            assert app.choice_kind is None
            assert app.setup_step is None
            assert app.config == config
            assert app.focused is prompt

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


def test_textual_picks_saved_provider_and_logs_out_inactive_profile() -> None:
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
            await pilot.press("down", "down", "enter")
            assert app.config == second
            prompt = app.query_one("#prompt")
            prompt.value = "/logout"
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("enter")
            assert store.load_all() == (second,)
            assert app.config == second

    asyncio.run(exercise())
