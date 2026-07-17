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

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> JsonObject:
        """Send one JSON GET request and return a JSON object response."""


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

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> JsonObject:
        try:
            request = Request(url, headers=dict(headers), method="GET")
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
        api_key: str | None = None,
        model: str | None = "gpt-4o",
        transport: JsonTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("provider base URL is required")
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=api_key,
            model=model,
            transport=transport or UrllibJsonTransport(),
        )

    def list_models(self) -> tuple[str, ...]:
        """Return model IDs exposed by the OpenAI-compatible endpoint."""
        return self._client.list_models()

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
        token: str | None,
        model: str | None,
        transport: JsonTransport,
    ) -> None:
        if model is not None and not model.strip():
            raise ProviderError("provider model is required")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._model = model
        self._transport = transport

    def list_models(self) -> tuple[str, ...]:
        try:
            result = self._transport.get(
                f"{self._base_url}/models",
                self._headers(content_type=False),
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("provider model discovery failed") from error
        raw_models = result.get("data")
        if not isinstance(raw_models, list):
            raise ProviderError("provider model response did not contain data")
        models: list[str] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, Mapping):
                raise ProviderError("provider model response contained an invalid model")
            model_id = raw_model.get("id")
            if not isinstance(model_id, str) or not model_id.strip():
                raise ProviderError("provider model response contained an invalid model ID")
            models.append(model_id)
        return tuple(models)

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition],
        model: str | None,
    ) -> ModelResponse:
        selected_model = model or self._model
        if not selected_model or not selected_model.strip():
            raise ProviderError("provider model is required")
        payload: dict[str, object] = {
            "model": selected_model,
            "messages": [_serialize_message(message) for message in messages],
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
                self._headers(),
                payload,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("provider request failed") from error
        if not isinstance(result, Mapping):
            raise ProviderError("provider response must be a JSON object")
        return _parse_response(result)

    def _headers(self, *, content_type: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _serialize_message(message: AgentMessage) -> dict[str, object]:
    raw_tool_call = getattr(message, "tool_call", None)
    if raw_tool_call is not None:
        serialized_tool_call: dict[str, object] = {
            "type": "function",
            "function": {
                "name": raw_tool_call.name,
                "arguments": json.dumps(dict(raw_tool_call.arguments)),
            },
        }
        if raw_tool_call.call_id is not None:
            serialized_tool_call["id"] = raw_tool_call.call_id
        return {
            "role": message.role,
            "content": message.content or None,
            "tool_calls": [serialized_tool_call],
        }

    serialized: dict[str, object] = {
        "role": message.role,
        "content": message.content,
    }
    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id is not None:
        serialized["tool_call_id"] = tool_call_id
    return serialized


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