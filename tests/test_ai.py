import json
from collections.abc import Mapping, Sequence
from typing import cast

import pytest

from peon.agent import (
    AgentMessage,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    Usage,
    run_task,
)
from peon.ai import (
    CustomProvider,
    CustomRequestFields,
    CustomResponseFields,
    GitHubCopilotProvider,
    OpenAICompatibleProvider,
    ProviderError,
    UrllibJsonTransport,
)
from peon.extensions import ExtensionRegistry, register_sample_tools


class StubTransport:
    def __init__(
        self,
        response: object,
        get_response: object | None = None,
        stream_lines: Sequence[str] | None = None,
    ) -> None:
        self.response = response
        self.get_response = get_response
        self.stream_lines = stream_lines
        self.url: str | None = None
        self.headers: Mapping[str, str] | None = None
        self.payload: Mapping[str, object] | None = None

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.url = url
        self.headers = headers
        self.payload = payload
        if isinstance(self.response, Exception):
            raise self.response
        return cast(Mapping[str, object], self.response)

    def stream_post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ):
        self.url = url
        self.headers = headers
        self.payload = payload
        if isinstance(self.response, Exception):
            raise self.response
        if self.stream_lines is not None:
            yield from self.stream_lines

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> Mapping[str, object]:
        self.url = url
        self.headers = headers
        if isinstance(self.get_response, Exception):
            raise self.get_response
        return cast(Mapping[str, object], self.get_response)


class QueuedTransport(StubTransport):
    def __init__(self, responses: list[object]) -> None:
        super().__init__({})
        self.responses = responses
        self.payloads: list[Mapping[str, object]] = []

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        self.payloads.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return cast(Mapping[str, object], response)


def test_openai_compatible_provider_normalizes_request_and_text_response() -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": "Repository summarized."}}]}
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1/",
        api_key="openai-key",
        model="small-model",
        transport=transport,
    )
    messages = [AgentMessage(role="user", content="Summarize the repository.")]
    tools = [
        ToolDefinition(
            name="lookup",
            description="Look up a value.",
            parameters={"type": "object", "properties": {"key": {"type": "string"}}},
        )
    ]

    response = provider.complete(messages=messages, tools=tools)

    assert response == ModelResponse(content="Repository summarized.")
    assert transport.url == "https://example.test/v1/chat/completions"
    assert transport.headers == {
        "Authorization": "Bearer openai-key",
        "Content-Type": "application/json",
        "User-Agent": "peon",
    }
    assert transport.payload is not None
    assert transport.payload["model"] == "small-model"
    assert transport.payload["messages"] == [
        {"role": "user", "content": "Summarize the repository."}
    ]
    assert transport.payload["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "lookup",
                "description": "Look up a value.",
                "parameters": {
                    "type": "object",
                    "properties": {"key": {"type": "string"}},
                },
            },
        }
    ]


def test_openai_provider_normalizes_complete_and_partial_usage() -> None:
    transport = QueuedTransport(
        [
            {
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "prompt_tokens_details": {"cached_tokens": 80},
                    "cost": 0.0042,
                    "currency": "USD",
                },
                "choices": [{"message": {"content": "Done."}}],
            },
            {
                "usage": {"prompt_tokens": 7},
                "choices": [{"message": {"content": "Partial."}}],
            },
        ]
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        model="usage-model",
        transport=transport,
    )

    complete = provider.complete(messages=[])
    partial = provider.complete(messages=[])

    assert complete.usage == Usage(
        input_tokens=120,
        output_tokens=30,
        cache_tokens=80,
        cost=0.0042,
        currency="USD",
    )
    assert partial.usage == Usage(input_tokens=7)


def test_openai_provider_leaves_unsupported_usage_unavailable() -> None:
    transport = StubTransport(
        {
            "usage": {"total_tokens": 12},
            "choices": [{"message": {"content": "Done."}}],
        }
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        model="usage-model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response.usage is None


def test_custom_provider_matches_corporate_chat_payload(monkeypatch) -> None:
    monkeypatch.setattr("peon.ai.provider_adapters.time.time", lambda: 1784295526)
    transport = StubTransport(
        {
            "service": "chat",
            "completion": "Corporate response.",
            "analysis": "The response is straightforward.",
        }
    )
    provider = CustomProvider(
        base_url="https://proxy.test/api/client-apps",
        api_key=None,
        model="corporate-model",
        response_fields=CustomResponseFields(thinking="analysis"),
        transport=transport,
    )

    response = provider.complete(
        messages=[AgentMessage(role="user", content="Hello")],
        tools=[
            ToolDefinition(
                name="lookup",
                description="Look up a value.",
                parameters={"type": "object"},
            )
        ],
    )

    assert response == ModelResponse(
        content="Corporate response.",
        thinking="The response is straightforward.",
    )
    assert transport.url == "https://proxy.test/api/client-apps"
    assert transport.headers == {
        "Content-Type": "application/json",
        "User-Agent": "peon",
    }
    assert transport.payload == {
        "version": 1,
        "service": "chat",
        "timestamp": 1784295526,
        "model": "corporate-model",
        "reasoningEffort": "low",
        "temperature": 1,
        "maxResponseTokens": 4096,
        "responseFormat": "text",
        "messages": [
            {
                "role": "user",
                "content": "Hello",
            },
            {
                "role": "developer",
                "content": "Peon provided callable tools through the tools field. When the next step requires using a tool, respond with only compact JSON in this exact shape: {\"tool_call\":{\"name\":\"tool_name\",\"arguments\":{...}}}. Use only listed tool names and arguments that match their schemas. Use only one tool call per response. When no tool is needed, respond with only: {\"final\":\"answer text\"}. Available tools: [{\"name\": \"lookup\", \"description\": \"Look up a value.\", \"parameters\": {\"type\": \"object\"}}]",
            },
        ],
    }


def test_custom_provider_normalizes_direct_response_usage() -> None:
    transport = StubTransport(
        {
            "completion": "Corporate response.",
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "cost": 0.002,
                "currency": "USD",
            },
        }
    )
    provider = CustomProvider(
        base_url="https://proxy.test/api/client-apps",
        model="corporate-model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response.usage == Usage(
        input_tokens=12,
        output_tokens=5,
        cost=0.002,
        currency="USD",
    )


def test_custom_provider_supports_configured_request_field_and_embedding(monkeypatch) -> None:
    monkeypatch.setattr("peon.ai.provider_adapters.time.time", lambda: 1784295526)
    transport = StubTransport(
        {"embedding": [[1, 2.5], [3.25, 4]]}
    )
    provider = CustomProvider(
        base_url="http://localhost:8080",
        model="embed-model",
        request_fields=CustomRequestFields(reasoning_effort="reasoning_effort"),
        transport=transport,
    )

    embeddings = provider.embed(["hello", "world"])

    assert embeddings == ((1.0, 2.5), (3.25, 4.0))
    assert transport.url == "http://localhost:8080"
    assert transport.payload == {
        "version": 1,
        "service": "embedding",
        "timestamp": 1784295526,
        "model": "embed-model",
        "contents": ["hello", "world"],
    }


def test_custom_provider_uses_configured_corporate_field_names() -> None:
    transport = StubTransport({"completion": "Configured response."})
    provider = CustomProvider(
        base_url="http://localhost:8080",
        model="chat-model",
        request_fields=CustomRequestFields(
            reasoning_effort="reasoning_effort",
            temperature="temp",
            max_response_tokens="max_tokens",
            response_format="response_format",
        ),
        reasoning_effort="high",
        temperature=0.2,
        max_response_tokens=2048,
        response_format="json_object",
        transport=transport,
    )

    provider.complete(messages=[AgentMessage(role="user", content="Hello")])

    assert transport.payload is not None
    assert transport.payload["reasoning_effort"] == "high"
    assert transport.payload["temp"] == 0.2
    assert transport.payload["max_tokens"] == 2048
    assert transport.payload["response_format"] == "json_object"


def test_custom_provider_can_place_tool_prompt_in_system_role() -> None:
    transport = StubTransport({"completion": "Configured response."})
    provider = CustomProvider(
        base_url="http://localhost:8080",
        model="chat-model",
        tool_prompt_role="system",
        transport=transport,
    )

    provider.complete(
        messages=[AgentMessage(role="user", content="Hello")],
        tools=[
            ToolDefinition(
                name="lookup",
                description="Look up a value.",
                parameters={"type": "object"},
            )
        ],
    )

    assert transport.payload is not None
    assert transport.payload["messages"][1]["role"] == "system"  # type: ignore[index]


def test_custom_provider_parses_ai_bridge_tool_call_completion() -> None:
    transport = StubTransport(
        {
            "completion": '{"tool_call":{"name":"lookup","arguments":{"key":"owner"}}}'
        }
    )
    provider = CustomProvider(
        base_url="http://localhost:8080",
        model="chat-model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response == ModelResponse(
        tool_call=ToolCall(name="lookup", arguments={"key": "owner"})
    )


def test_word_count_fallback_turn_executes_and_returns_final_answer() -> None:
    transport = QueuedTransport(
        [
            {
                "completion": (
                    '{"tool_call":{"name":"word_count",'
                    '"arguments":{"text":"one two three"}}}'
                )
            },
            {"completion": '{"final":"There are three words."}'},
        ]
    )
    provider = CustomProvider(
        base_url="http://localhost:8080",
        model="chat-model",
        transport=transport,
    )
    registry = ExtensionRegistry()
    register_sample_tools(registry)

    result = run_task(
        "Count the words in one two three.",
        provider,
        executor=registry,
    )

    assert result == "There are three words."
    assert len(transport.payloads) == 2
    second_messages = transport.payloads[1]["messages"]
    assert isinstance(second_messages, list)
    assert second_messages[-3:-1] == [
        {
            "role": "assistant",
            "content": (
                '{"tool_call":{"name":"word_count",'
                '"arguments":{"text":"one two three"}}}'
            ),
        },
        {"role": "tool", "content": "word count: 3"},
    ]


def test_openai_provider_applies_config_and_wraps_tools_when_unsupported() -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": "Configured response."}}]}
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1/chat",
        model="chat-model",
        reasoning_effort="high",
        temperature=0.4,
        max_completion_tokens=1024,
        max_output_tokens=2048,
        max_tokens=4096,
        response_format="json_object",
        supports_tools=False,
        supports_chat_completions=False,
        transport=transport,
    )

    provider.complete(
        messages=[AgentMessage(role="user", content="Hello")],
        tools=[
            ToolDefinition(
                name="lookup",
                description="Look up a value.",
                parameters={"type": "object"},
            )
        ],
    )

    assert transport.url == "https://example.test/v1/chat"
    assert transport.payload is not None
    assert transport.payload["reasoning_effort"] == "high"
    assert transport.payload["temperature"] == 0.4
    assert transport.payload["max_completion_tokens"] == 1024
    assert transport.payload["max_output_tokens"] == 2048
    assert transport.payload["max_tokens"] == 4096
    assert transport.payload["response_format"] == {"type": "json_object"}
    assert "tools" not in transport.payload
    assert transport.payload["messages"][1]["role"] == "developer"  # type: ignore[index]


def test_custom_provider_uses_chat_suffix_and_configured_response_path() -> None:
    transport = StubTransport({"result": {"message": "Mapped response."}})
    provider = CustomProvider(
        base_url="https://proxy.test/v1/",
        model="chat-model",
        response_fields=CustomResponseFields(content="result.message"),
        supports_chat_completions=True,
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response == ModelResponse(content="Mapped response.")
    assert transport.url == "https://proxy.test/v1/chat/completions"


def test_custom_provider_discovers_models_and_prepares_streaming_surface() -> None:
    transport = StubTransport(
        {},
        get_response={"data": [{"id": "chat-model"}, {"id": "embed-model"}]},
    )
    provider = CustomProvider(
        base_url="https://proxy.test",
        transport=transport,
    )

    assert provider.list_models() == ("chat-model", "embed-model")
    with pytest.raises(ProviderError, match="streaming is not available"):
        provider.complete_stream()


def test_openai_compatible_provider_allows_optional_api_key() -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": "Local response."}}]}
    )
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1",
        api_key=None,
        model="local-model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response == ModelResponse(content="Local response.")
    assert transport.headers == {
        "Content-Type": "application/json",
        "User-Agent": "peon",
    }


def test_openai_compatible_provider_discovers_available_models() -> None:
    transport = StubTransport(
        {},
        get_response={
            "data": [
                {"id": "local-small"},
                {"id": "local-large"},
            ]
        },
    )
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:11434/v1/",
        api_key=None,
        model=None,
        transport=transport,
    )

    models = provider.list_models()

    assert models == ("local-small", "local-large")
    assert transport.url == "http://localhost:11434/v1/models"
    assert transport.headers == {"User-Agent": "peon"}


def test_openai_compatible_provider_normalizes_tool_call_response() -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"key":"owner"}',
                                },
                            }
                        ],
                    }
                }
            ]
        }
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response.content == ""
    assert response.tool_call is not None
    assert response.tool_call.name == "lookup"
    assert response.tool_call.arguments == {"key": "owner"}
    assert response.tool_call.call_id == "call-1"


def test_openai_compatible_provider_serializes_tool_continuation_messages() -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": "The owner is Peon."}}]}
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=transport,
    )

    provider.complete(
        messages=[
            AgentMessage(role="user", content="Who owns the project?"),
            AgentMessage(
                role="assistant",
                content="",
                tool_call=ToolCall(
                    name="lookup",
                    arguments={"key": "owner"},
                    call_id="call-1",
                ),
            ),
            AgentMessage(
                role="tool",
                content="owner:owner",
                tool_call_id="call-1",
            ),
        ]
    )

    assert transport.payload is not None
    assert transport.payload["messages"] == [
        {"role": "user", "content": "Who owns the project?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": "lookup",
                        "arguments": '{"key": "owner"}',
                    },
                    "id": "call-1",
                }
            ],
        },
        {
            "role": "tool",
            "content": "owner:owner",
            "tool_call_id": "call-1",
        },
    ]


def test_github_copilot_provider_keeps_login_token_inside_adapter(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GITHUB_COPILOT_TOKEN", "copilot-login-token")
    transport = StubTransport(
        {"choices": [{"message": {"content": "Copilot response."}}]}
    )
    provider = GitHubCopilotProvider(
        model="copilot-model",
        transport=transport,
    )

    response = provider.complete(messages=[])

    assert response.content == "Copilot response."
    assert transport.headers is not None
    assert transport.headers["Authorization"] == "Bearer copilot-login-token"


@pytest.mark.parametrize(
    ("provider_factory", "message"),
    [
        (
            lambda transport: OpenAICompatibleProvider(
                base_url="", api_key="key", model="model", transport=transport
            ),
            "base URL is required",
        ),
    ],
)
def test_provider_rejects_invalid_configuration(provider_factory, message) -> None:
    with pytest.raises(ProviderError, match=message):
        provider_factory(StubTransport({}))


def test_provider_rejects_missing_copilot_login(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_COPILOT_TOKEN", raising=False)

    with pytest.raises(ProviderError, match="login token"):
        GitHubCopilotProvider(transport=StubTransport({}))


def test_provider_wraps_copilot_login_failure() -> None:
    def failing_login() -> str:
        raise RuntimeError("login unavailable")

    with pytest.raises(ProviderError, match="login failed"):
        GitHubCopilotProvider(
            token_provider=failing_login,
            transport=StubTransport({}),
        )


def test_provider_wraps_transport_failures() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=StubTransport(RuntimeError("connection refused")),
    )

    with pytest.raises(ProviderError, match="request failed"):
        provider.complete(messages=[])


def test_provider_wraps_non_object_transport_responses() -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=StubTransport([]),
    )

    with pytest.raises(ProviderError, match="response"):
        provider.complete(messages=[])


def test_provider_wraps_request_serialization_failures() -> None:
    class UnserializableMessage:
        role = "user"
        content = object()

    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=UrllibJsonTransport(),
    )

    with pytest.raises(ProviderError, match="request failed"):
        provider.complete(
            messages=cast(Sequence[AgentMessage], [UnserializableMessage()])
        )


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"function": {"name": "lookup", "arguments": "[]"}}
                        ]
                    }
                }
            ]
        },
    ],
)
def test_provider_rejects_invalid_response_shape(response) -> None:
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=StubTransport(response),
    )

    with pytest.raises(ProviderError, match="response"):
        provider.complete(messages=[])


def test_openai_compatible_provider_streams_response_and_reconciles_canonical_message() -> None:
    lines = [
        'data: {"choices": [{"delta": {"thinking": "Thinking..."}}]}',
        'data: {"choices": [{"delta": {"content": "Hello"}}]}',
        'data: {"choices": [{"delta": {"content": " world!"}}]}',
        'data: {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}',
        'data: [DONE]',
    ]
    transport = StubTransport({}, stream_lines=lines)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=transport,
    )

    chunks = list(provider.stream(messages=[]))
    assert len(chunks) == 4
    assert chunks[0].thinking_delta == "Thinking..."
    assert chunks[1].delta == "Hello"
    assert chunks[2].delta == " world!"
    assert chunks[3].usage == Usage(input_tokens=10, output_tokens=5)

    result = run_task("hello", provider)
    assert result == "Hello world!"


def test_custom_provider_does_not_advertise_streaming() -> None:
    provider = CustomProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
    )
    assert not hasattr(provider, "stream") or not callable(getattr(provider, "stream", None))