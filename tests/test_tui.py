from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO

from peon.agent import AgentMessage, ModelResponse, ToolDefinition
from peon.app import JsonProviderConfigStore, ProviderConfig
from peon.app.tui import _resolve_command, run_tui


@dataclass
class FakeProvider:
    responses: list[str]
    received_messages: list[tuple[AgentMessage, ...]]
    received_tools: list[tuple[ToolDefinition, ...]]
    models: tuple[str, ...] = ()

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

    def list_models(self) -> tuple[str, ...]:
        return self.models


class ProviderFactory:
    def __init__(self) -> None:
        self.configurations: list[ProviderConfig] = []
        self.providers: list[FakeProvider] = []

    def __call__(self, config: ProviderConfig) -> FakeProvider:
        self.configurations.append(config)
        if config.model is None:
            responses = []
        elif config.name == "github-copilot":
            responses = ["reconfigured response"]
        else:
            responses = ["first response", "second response"]
        provider = FakeProvider(
            responses=responses,
            received_messages=[],
            received_tools=[],
            models=("first-model", "second-model"),
        )
        self.providers.append(provider)
        return provider


@dataclass
class MemoryConfigStore:
    configuration: ProviderConfig | None = None

    def load(self) -> ProviderConfig | None:
        return self.configuration

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return (self.configuration,) if self.configuration is not None else ()

    def save(self, config: ProviderConfig) -> None:
        self.configuration = config

    def delete(self, config: ProviderConfig) -> None:
        if self.configuration == config:
            self.configuration = None


def scripted_input(values: list[str]):
    iterator = iter(values)
    return lambda prompt: next(iterator)


def scripted_secret(values: list[str]):
    iterator = iter(values)
    return lambda prompt: next(iterator)


def test_tui_configures_provider_and_keeps_context_between_tasks() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "https://example.test/v1",
                "1",
                "first task",
                "second task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations == [
        ProviderConfig(
            name="openai-compatible",
            base_url="https://example.test/v1",
            api_key="api-key",
        ),
        ProviderConfig(
            name="openai-compatible",
            model="first-model",
            models=("first-model", "second-model"),
            base_url="https://example.test/v1",
            api_key="api-key",
        ),
    ]
    assert " peon v0.1.0" in output.getvalue()
    assert "minimal" in output.getvalue()
    assert output.getvalue().count("─") >= 2
    assert output.getvalue().count("first response") == 1
    assert output.getvalue().count("second response") == 1
    assert [tool.name for tool in factory.providers[1].received_tools[0]] == [
        "word_count"
    ]
    assert factory.providers[1].received_messages[1] == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )


def test_tui_can_replace_provider_from_provider_command() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "https://first.example/v1",
                "1",
                "/provider",
                "2",
                "first task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["first-key", "copilot-token"]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations == [
        ProviderConfig(
            name="openai-compatible",
            base_url="https://first.example/v1",
            api_key="first-key",
        ),
        ProviderConfig(
            name="openai-compatible",
            model="first-model",
            models=("first-model", "second-model"),
            base_url="https://first.example/v1",
            api_key="first-key",
        ),
        ProviderConfig(
            name="github-copilot",
            copilot_token="copilot-token",
        ),
        ProviderConfig(
            name="github-copilot",
            model="gpt-4o",
            copilot_token="copilot-token",
        ),
    ]
    assert output.getvalue().count("first response") == 0
    assert output.getvalue().count("reconfigured response") == 1
    assert config_store.configuration == ProviderConfig(
        name="github-copilot",
        model="gpt-4o",
        copilot_token="copilot-token",
    )


def test_tui_supports_help_tools_and_clear_commands() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "https://example.test/v1",
                "1",
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
        config_store=config_store,
    )

    assert result == 0
    rendered = output.getvalue()
    assert "- word_count: Count the whitespace-separated words in a text value." in rendered
    assert "/provider  configure a provider" in rendered
    assert "Conversation cleared." in rendered
    assert factory.providers[1].received_messages[1] == (
        AgentMessage(role="user", content="second task"),
    )


def test_tui_auto_discovers_and_selects_openai_compatible_model() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "http://localhost:11434/v1",
                "2",
                "/quit",
            ]
        ),
        secret_input=scripted_secret([""]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations[0].model is None
    assert factory.configurations[1].model == "second-model"
    assert "first-model" in output.getvalue()
    assert "second-model" in output.getvalue()
    assert config_store.configuration is not None
    assert config_store.configuration.models == ("first-model", "second-model")


def test_tui_reuses_saved_provider_configuration() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore(
        configuration=ProviderConfig(
            name="openai-compatible",
            model="saved-model",
            base_url="http://localhost:11434/v1",
            api_key=None,
        )
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(["saved task", "/quit"]),
        secret_input=scripted_secret([]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations == [config_store.configuration]
    assert "Using saved provider: openai-compatible (saved-model)" in output.getvalue()


def test_tui_lists_and_switches_saved_models() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore(
        configuration=ProviderConfig(
            name="openai-compatible",
            model="first-model",
            models=("first-model", "second-model"),
            base_url="http://localhost:11434/v1",
        )
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(["/models", "/model 2", "/quit"]),
        secret_input=scripted_secret([]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations[-1].model == "second-model"
    assert config_store.configuration is not None
    assert config_store.configuration.model == "second-model"
    assert "1. first-model" in output.getvalue()
    assert "Model selected: second-model" in output.getvalue()


def test_tui_runs_first_matching_abbreviated_command() -> None:
    factory = ProviderFactory()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "https://example.test/v1",
                "1",
                "/he",
                "/cl",
                "/q",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=output,
        config_store=MemoryConfigStore(),
    )

    assert result == 0
    assert "/provider  configure a provider" in output.getvalue()
    assert "Conversation cleared." in output.getvalue()
    assert "Goodbye." in output.getvalue()


def test_tui_logout_removes_saved_provider_and_exits() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore(
        configuration=ProviderConfig(
            name="openai-compatible",
            model="first-model",
            models=("first-model", "second-model"),
            base_url="http://localhost:11434/v1",
        )
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "/logout",
                "1",
                "http://localhost:11434/v1",
                "1",
                "/quit",
            ]
        ),
        secret_input=scripted_secret([""]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert config_store.configuration is not None
    assert config_store.configuration.base_url == "http://localhost:11434/v1"
    assert "Saved provider removed: openai-compatible." in output.getvalue()


def test_command_resolution_prefers_first_matching_command() -> None:
    assert _resolve_command("/mo") == "/model"
    assert _resolve_command("/q") == "/quit"
    assert _resolve_command("/missing") is None


def test_json_provider_config_store_round_trips(tmp_path) -> None:
    config = ProviderConfig(
        name="openai-compatible",
        model="local-model",
        base_url="http://localhost:11434/v1",
        api_key="local-key",
    )
    store = JsonProviderConfigStore(tmp_path / "provider.json")

    store.save(config)

    assert store.load() == config


def test_json_provider_config_store_ignores_malformed_profile(tmp_path) -> None:
    profile_path = tmp_path / "provider.json"
    profile_path.write_text("not json", encoding="utf-8")
    store = JsonProviderConfigStore(profile_path)

    assert store.load() is None