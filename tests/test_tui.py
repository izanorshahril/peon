from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO

from peon.agent import AgentMessage, ModelResponse, ToolDefinition
from peon.app import ProviderConfig
from peon.app.tui import run_tui


@dataclass
class FakeProvider:
    responses: list[str]
    received_messages: list[tuple[AgentMessage, ...]]
    received_tools: list[tuple[ToolDefinition, ...]]

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages.append(tuple(messages))
        self.received_tools.append(tuple(tools))
        return ModelResponse(content=self.responses.pop(0))


class ProviderFactory:
    def __init__(self) -> None:
        self.configurations: list[ProviderConfig] = []
        self.providers: list[FakeProvider] = []

    def __call__(self, config: ProviderConfig) -> FakeProvider:
        self.configurations.append(config)
        responses = (
            ["first response", "second response"]
            if not self.providers
            else ["reconfigured response"]
        )
        provider = FakeProvider(
            responses=responses,
            received_messages=[],
            received_tools=[],
        )
        self.providers.append(provider)
        return provider


def scripted_input(values: list[str]):
    iterator = iter(values)
    return lambda prompt: next(iterator)


def scripted_secret(values: list[str]):
    iterator = iter(values)
    return lambda prompt: next(iterator)


def test_tui_configures_provider_and_keeps_context_between_tasks() -> None:
    factory = ProviderFactory()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "openai-compatible",
                "small-model",
                "https://example.test/v1",
                "first task",
                "second task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=output,
    )

    assert result == 0
    assert factory.configurations == [
        ProviderConfig(
            name="openai-compatible",
            model="small-model",
            base_url="https://example.test/v1",
            api_key="api-key",
        )
    ]
    assert output.getvalue().count("first response") == 1
    assert output.getvalue().count("second response") == 1
    assert [tool.name for tool in factory.providers[0].received_tools[0]] == [
        "word_count"
    ]
    assert factory.providers[0].received_messages[1] == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )


def test_tui_can_replace_provider_from_provider_command() -> None:
    factory = ProviderFactory()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "openai-compatible",
                "first-model",
                "https://first.example/v1",
                "/provider",
                "github-copilot",
                "second-model",
                "first task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["first-key", "copilot-token"]),
        output=output,
    )

    assert result == 0
    assert factory.configurations == [
        ProviderConfig(
            name="openai-compatible",
            model="first-model",
            base_url="https://first.example/v1",
            api_key="first-key",
        ),
        ProviderConfig(
            name="github-copilot",
            model="second-model",
            copilot_token="copilot-token",
        ),
    ]
    assert output.getvalue().count("first response") == 0
    assert output.getvalue().count("reconfigured response") == 1


def test_tui_supports_help_tools_and_clear_commands() -> None:
    factory = ProviderFactory()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "openai-compatible",
                "small-model",
                "https://example.test/v1",
                "/tools",
                "/help",
                "first task",
                "/clear",
                "second task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=output,
    )

    assert result == 0
    rendered = output.getvalue()
    assert "- word_count: Count the whitespace-separated words in a text value." in rendered
    assert "/provider  configure a provider" in rendered
    assert "Conversation cleared." in rendered
    assert factory.providers[0].received_messages[1] == (
        AgentMessage(role="user", content="second task"),
    )