"""OpenAI-compatible provider adapters for Peon."""

from collections.abc import Callable, Mapping, Sequence
import json
import os
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition

from .errors import ProviderError

JsonObject = Mapping[str, object]


class JsonTransport(Protocol):
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> JsonObject:
        """Send one JSON request and return a JSON object response."""


class UrllibJsonTransport:
    """Standard-library JSON POST transport for provider adapters."""

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> JsonObject:
        try:
            request = Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=dict(headers),
                method="POST",
            )
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise ProviderError(f"provider request failed: {url}") from error
        if not isinstance(result, Mapping):
            raise ProviderError("provider response must be a JSON object")
        return result


class OpenAICompatibleProvider:
    """Use an OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "gpt-4o",
        transport: JsonTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("provider base URL is required")
        if not api_key.strip():
            raise ProviderError("provider API key is required")
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=api_key,
            model=model,
            transport=transport or UrllibJsonTransport(),
        )

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return self._client.complete(messages=messages, tools=tools, model=model)


class GitHubCopilotProvider:
    """Use GitHub Copilot chat completions with login credentials."""

    def __init__(
        self,
        *,
        token: str | None = None,
        model: str = "gpt-4o",
        base_url: str = "https://api.githubcopilot.com",
        transport: JsonTransport | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        try:
            resolved_token = token or (
                token_provider() if token_provider else None
            )
        except Exception as error:
            raise ProviderError("GitHub Copilot login failed") from error
        resolved_token = resolved_token or os.environ.get("GITHUB_COPILOT_TOKEN")
        if not resolved_token:
            raise ProviderError(
                "GitHub Copilot login token is not configured; provide a token "
                "or GITHUB_COPILOT_TOKEN"
            )
        if not base_url.strip():
            raise ProviderError("provider base URL is required")
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=resolved_token,
            model=model,
            transport=transport or UrllibJsonTransport(),
        )

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return self._client.complete(messages=messages, tools=tools, model=model)


class _ChatCompletionsClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        model: str,
        transport: JsonTransport,
    ) -> None:
        if not model.strip():
            raise ProviderError("provider model is required")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._model = model
        self._transport = transport

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
        model: str | None,
    ) -> ModelResponse:
        payload: dict[str, object] = {
            "model": model or self._model,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": dict(tool.parameters),
                    },
                }
                for tool in tools
            ]

        try:
            result = self._transport.post(
                f"{self._base_url}/chat/completions",
                {
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                payload,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("provider request failed") from error
        if not isinstance(result, Mapping):
            raise ProviderError("provider response must be a JSON object")
        return _parse_response(result)


def _parse_response(result: JsonObject) -> ModelResponse:
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderError("provider response did not contain choices")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ProviderError("provider response contained an invalid choice")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ProviderError("provider response did not contain a chat message")

    tool_call = _parse_tool_call(message.get("tool_calls"))
    content = message.get("content")
    if tool_call is not None:
        return ModelResponse(content=content if isinstance(content, str) else "", tool_call=tool_call)
    if isinstance(content, str) and content.strip():
        return ModelResponse(content=content)
    raise ProviderError("provider response did not contain text or a tool call")


def _parse_tool_call(value: object) -> ToolCall | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise ProviderError("provider response contained invalid tool calls")
    raw_call = value[0]
    if not isinstance(raw_call, Mapping):
        raise ProviderError("provider response contained an invalid tool call")
    function = raw_call.get("function")
    if not isinstance(function, Mapping):
        raise ProviderError("provider response contained an invalid tool function")
    name = function.get("name")
    raw_arguments = function.get("arguments")
    if not isinstance(name, str) or not name.strip():
        raise ProviderError("provider tool call did not contain a name")
    if isinstance(raw_arguments, str):
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as error:
            raise ProviderError("provider tool call arguments were invalid JSON") from error
    else:
        arguments = raw_arguments
    if not isinstance(arguments, Mapping):
        raise ProviderError(
            "provider response tool call arguments must be an object"
        )
    call_id = raw_call.get("id")
    if call_id is not None and not isinstance(call_id, str):
        raise ProviderError("provider tool call id must be a string")
    return ToolCall(name=name, arguments=arguments, call_id=call_id)