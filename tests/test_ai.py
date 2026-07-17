import json
from collections.abc import Mapping, Sequence
from typing import cast

import pytest

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition
from peon.ai import (
    GitHubCopilotProvider,
    OpenAICompatibleProvider,
    ProviderError,
    UrllibJsonTransport,
)


class StubTransport:
    def __init__(self, response: object) -> None:
        self.response = response
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
        (
            lambda transport: OpenAICompatibleProvider(
                base_url="https://example.test",
                api_key="",
                model="model",
                transport=transport,
            ),
            "API key is required",
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