from collections.abc import Sequence
from dataclasses import dataclass
from io import StringIO

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from peon.app import JsonProviderConfigStore, ProviderConfig
from peon.app.tui import SlashCommandCompleter, run_tui
from peon.app.sessions import JsonlSessionStore, MemorySessionStore
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document


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


class ToolCallingProvider(FakeProvider):
    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(responses=[], received_messages=[], received_tools=[])
        self.model_responses = responses

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages.append(tuple(messages))
        self.received_tools.append(tuple(tools))
        return self.model_responses.pop(0)

    def list_models(self) -> tuple[str, ...]:
        return ("first-model",)


class ToolCallingFactory:
    def __init__(self) -> None:
        self.providers: list[ToolCallingProvider] = []

    def __call__(self, config: ProviderConfig) -> ToolCallingProvider:
        provider = ToolCallingProvider(
            [
                ModelResponse(
                    tool_call=ToolCall(
                        name="word_count",
                        arguments={"text": "one two three"},
                    )
                ),
                ModelResponse(content="There are three words."),
            ]
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


@dataclass
class MultiMemoryConfigStore:
    configurations: list[ProviderConfig]
    active: ProviderConfig

    def load(self) -> ProviderConfig:
        return self.active

    def load_all(self) -> tuple[ProviderConfig, ...]:
        return tuple(self.configurations)

    def save(self, config: ProviderConfig) -> None:
        for index, existing in enumerate(self.configurations):
            if existing.name == config.name and existing.base_url == config.base_url:
                self.configurations[index] = config
                self.active = config
                return
        self.configurations.append(config)
        self.active = config

    def delete(self, config: ProviderConfig) -> None:
        self.configurations = [
            existing
            for existing in self.configurations
            if existing != config
        ]
        if self.active == config and self.configurations:
            self.active = self.configurations[0]


class FailOnceSessionStore(MemorySessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def append(self, session_id: str, message: AgentMessage) -> None:
        if not self.failed:
            self.failed = True
            raise OSError("storage temporarily unavailable")
        super().append(session_id, message)


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
        "word_count",
        "read",
        "ls",
        "find",
        "grep",
    ]
    assert factory.providers[1].received_messages[1] == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )


def test_tui_executes_native_word_count_and_renders_final_response() -> None:
    factory = ToolCallingFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "1",
                "https://example.test/v1",
                "1",
                "count the words",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert "There are three words." in output.getvalue()
    assert "unhandled tool" not in output.getvalue()
    assert factory.providers[1].received_messages[1][-2:] == (
        AgentMessage(
            role="assistant",
            content="",
            tool_call=ToolCall(
                name="word_count",
                arguments={"text": "one two three"},
            ),
        ),
        AgentMessage(role="tool", content="word count: 3"),
    )


def test_tui_resumes_sessions_and_new_preserves_previous_conversation() -> None:
    config_store = MemoryConfigStore()
    session_store = MemorySessionStore()
    first_factory = ProviderFactory()
    run_tui(
        provider_factory=first_factory,
        input_fn=scripted_input(
            [
                "1",
                "https://example.test/v1",
                "1",
                "first task",
                "/quit",
            ]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=StringIO(),
        config_store=config_store,
        session_store=session_store,
    )
    first_session = session_store.load_latest()
    assert first_session is not None
    assert first_session.messages[0] == AgentMessage(
        role="user", content="first task"
    )

    second_factory = ProviderFactory()
    run_tui(
        provider_factory=second_factory,
        input_fn=scripted_input(["second task", "/new", "/quit"]),
        secret_input=scripted_secret([]),
        output=StringIO(),
        config_store=config_store,
        session_store=session_store,
    )

    resumed_messages = second_factory.providers[0].received_messages[0]
    assert resumed_messages == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )
    assert len(session_store.order) == 2
    assert session_store.load(first_session.session_id).messages == (
        *first_session.messages,
        AgentMessage(role="user", content="second task"),
        AgentMessage(role="assistant", content="first response"),
    )
    latest = session_store.load_latest()
    assert latest is not None
    assert latest.session_id != first_session.session_id
    assert latest.messages == ()


def test_tui_resumes_jsonl_session_after_process_restart(tmp_path) -> None:
    config_store = MemoryConfigStore()
    session_store = JsonlSessionStore(tmp_path / "sessions")
    run_tui(
        provider_factory=ProviderFactory(),
        input_fn=scripted_input(
            ["1", "https://example.test/v1", "1", "first task", "/quit"]
        ),
        secret_input=scripted_secret(["api-key"]),
        output=StringIO(),
        config_store=config_store,
        session_store=session_store,
    )

    second_factory = ProviderFactory()
    run_tui(
        provider_factory=second_factory,
        input_fn=scripted_input(["second task", "/quit"]),
        secret_input=scripted_secret([]),
        output=StringIO(),
        config_store=config_store,
        session_store=JsonlSessionStore(tmp_path / "sessions"),
    )

    assert second_factory.providers[0].received_messages[0] == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )


def test_tui_retries_unsaved_messages_on_the_next_task() -> None:
    config_store = MemoryConfigStore()
    session_store = FailOnceSessionStore()
    run_tui(
        provider_factory=ProviderFactory(),
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
        output=StringIO(),
        config_store=config_store,
        session_store=session_store,
    )

    saved = session_store.load_latest()
    assert saved is not None
    assert saved.messages == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
        AgentMessage(role="assistant", content="second response"),
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


def test_tui_configures_named_custom_provider_and_request_field() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore()
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "3",
                "Corporate proxy",
                "http://localhost:8080/chat",
                "1",
                "/quit",
            ]
        ),
        secret_input=scripted_secret([""]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert factory.configurations[0] == ProviderConfig(
        name="Corporate proxy",
        provider_type="custom",
        base_url="http://localhost:8080/chat",
    )
    assert factory.configurations[1] == ProviderConfig(
        name="Corporate proxy",
        provider_type="custom",
        model="first-model",
        models=("first-model", "second-model"),
        base_url="http://localhost:8080/chat",
    )
    assert config_store.configuration == factory.configurations[1]


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


def test_tui_changes_custom_provider_settings() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore(
        configuration=ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "/settings",
                "2",
                "1",
                "1",
                "3",
                "1",
                "reasoning_effort",
                "",
                "",
                "",
                "/quit",
            ]
        ),
        secret_input=scripted_secret([]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert config_store.configuration is not None
    assert config_store.configuration.reasoning_effort_field == "reasoning_effort"
    assert factory.configurations[-1] == config_store.configuration
    assert "Updated reasoning_effort." in output.getvalue()


def test_tui_changes_active_provider_config_with_slash_commands() -> None:
    factory = ProviderFactory()
    config_store = MemoryConfigStore(
        configuration=ProviderConfig(
            name="Corporate",
            provider_type="custom",
            model="chat-model",
            base_url="http://localhost:8080",
        )
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            [
                "/temperature 0.4",
                "/reasoning high",
                "/supports-tools",
                "/quit",
            ]
        ),
        secret_input=scripted_secret([]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert config_store.configuration is not None
    assert config_store.configuration.temperature == 0.4
    assert config_store.configuration.reasoning_effort == "high"
    assert config_store.configuration.supports_tools is True
    assert factory.configurations[-1] == config_store.configuration


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


def test_tui_aggregates_saved_models_and_switches_provider_without_losing_context() -> None:
    factory = ProviderFactory()
    first = ProviderConfig(
        name="first provider",
        model="alpha",
        models=("alpha",),
        base_url="http://first.example/v1",
    )
    second = ProviderConfig(
        name="second provider",
        model="beta",
        models=("beta",),
        base_url="http://second.example/v1",
    )
    config_store = MultiMemoryConfigStore([first, second], active=second)
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(
            ["first task", "/models", "/model 1", "second task", "/quit"]
        ),
        secret_input=scripted_secret([]),
        output=output,
        config_store=config_store,
    )

    assert result == 0
    assert config_store.active == first
    assert factory.configurations[-1] == first
    assert "alpha [first provider]" in output.getvalue()
    assert "beta [second provider]" in output.getvalue()
    assert factory.providers[-1].received_messages[0] == (
        AgentMessage(role="user", content="first task"),
        AgentMessage(role="assistant", content="first response"),
        AgentMessage(role="user", content="second task"),
    )


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


def test_prompt_completer_does_not_replace_typed_arguments() -> None:
    completer = SlashCommandCompleter()

    completions = tuple(
        completer.get_completions(
            Document("/model 2"),
            CompleteEvent(completion_requested=True),
        )
    )

    assert completions == ()


def test_reserved_command_does_not_enter_agent_conversation() -> None:
    factory = ProviderFactory()
    config = ProviderConfig(
        name="openai-compatible",
        model="first-model",
        base_url="https://example.test/v1",
    )
    output = StringIO()

    result = run_tui(
        provider_factory=factory,
        input_fn=scripted_input(["/compact", "/quit"]),
        secret_input=scripted_secret([]),
        output=output,
        config_store=MemoryConfigStore(configuration=config),
    )

    assert result == 0
    assert "/compact is reserved and is not available yet." in output.getvalue()
    assert factory.providers[-1].received_messages == []


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