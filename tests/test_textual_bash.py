import asyncio

from peon.agent import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolExecutionContext,
)
from peon.app import ProviderConfig, UiConfig
from peon.app.textual_tui import ChatMessage, TextualPeonApp
from peon.extensions import ExtensionRegistry


class MemoryConfigStore:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def load(self) -> ProviderConfig:
        return self.config

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return (self.config,)

    def save(self, config: ProviderConfig) -> None:
        self.config = config

    def delete(self, config: ProviderConfig) -> None:
        del config

    def load_ui(self) -> UiConfig:
        return UiConfig()

    def save_ui(self, config: UiConfig) -> None:
        del config

    def update(self, previous: ProviderConfig, config: ProviderConfig) -> None:
        del previous
        self.config = config


class FakeProvider:
    def complete(self, *, messages, tools=(), model=None) -> ModelResponse:
        del messages, tools, model
        return ModelResponse(content="unused")


def test_textual_bash_output_stays_compact_and_expands_without_rerun() -> None:
    async def exercise() -> None:
        config = ProviderConfig(
            name="openai-compatible",
            model="alpha",
            base_url="https://example.test/v1",
        )
        app = TextualPeonApp(
            provider_factory=lambda _config: FakeProvider(),
            config_store=MemoryConfigStore(config),
            registry=ExtensionRegistry(),
        )
        call = ToolCall(
            name="bash",
            arguments={"command": "echo hello", "timeout": 1},
            call_id="bash-1",
        )
        result = AgentMessage(
            role="tool",
            content=(
                "bash: exit code 0\n"
                "status: exited\n"
                "stdout:\nhello\n"
                "Took 0.0s"
            ),
            tool_call_id="bash-1",
        )

        async with app.run_test() as pilot:
            app._append_context_message(
                AgentMessage(role="assistant", content="", tool_call=call)
            )
            execution_context = ToolExecutionContext()
            app.execution_context = execution_context
            app._append_bash_output(execution_context, "stdout", "live hello\n")
            transcript = app.query_one("#transcript", ChatMessage)
            assert "$ echo hello (timeout 1s)" in transcript.text
            assert "live hello" in transcript.text

            app._append_context_message(result)
            assert transcript.text.count("$ echo hello (timeout 1s)") == 1
            assert "hello" in transcript.text

            transcript.set_tools_expanded(True)
            assert "status: exited" in transcript.text
            assert "stdout:" in transcript.text
            assert "Took 0.0s" in transcript.text

            await pilot.pause()

    asyncio.run(exercise())