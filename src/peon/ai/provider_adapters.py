"""OpenAI-compatible provider adapters for Peon."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
import time
from typing import Literal, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from peon.agent import AgentMessage, ModelResponse, ToolCall, ToolDefinition, Usage

from .provider_errors import ProviderError

JsonObject = Mapping[str, object]
ToolPromptRole = Literal["system", "developer"]
PEON_USER_AGENT = "peon"


class JsonTransport(Protocol):
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: JsonObject,
    ) -> JsonObject:
        """Send one JSON request and return a JSON object response."""
        ...

    def get(
        self,
        url: str,
        headers: Mapping[str, str],
    ) -> JsonObject:
        """Send one JSON GET request and return a JSON object response."""
        ...


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
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_tokens: int | None = None,
        response_format: str | None = None,
        supports_tools: bool = True,
        supports_chat_completions: bool = True,
        tool_prompt_role: str = "developer",
        transport: JsonTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("provider base URL is required")
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=api_key,
            model=model,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            max_output_tokens=max_output_tokens,
            max_tokens=max_tokens,
            response_format=response_format,
            supports_tools=supports_tools,
            supports_chat_completions=supports_chat_completions,
            tool_prompt_role=_resolve_tool_prompt_role(tool_prompt_role),
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


@dataclass(frozen=True, slots=True)
class CustomRequestFields:
    """Request field names used by the custom service proxy."""

    reasoning_effort: str | None = "reasoningEffort"
    temperature: str | None = "temperature"
    max_response_tokens: str | None = "maxResponseTokens"
    max_output_tokens: str | None = "maxOutputTokens"
    max_tokens: str | None = "maxTokens"
    response_format: str | None = "responseFormat"


@dataclass(frozen=True, slots=True)
class CustomResponseFields:
    """Response paths used by the custom service proxy."""

    content: str = "completion"
    thinking: str = "thinking"


class CustomProvider:
    """Use a corporate-style service endpoint through a user-owned proxy."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        request_fields: CustomRequestFields | None = None,
        response_fields: CustomResponseFields | None = None,
        reasoning_effort: str | None = "low",
        temperature: float | None = 1,
        max_response_tokens: int | None = 4096,
        max_output_tokens: int | None = None,
        max_tokens: int | None = None,
        response_format: str | None = "text",
        supports_tools: bool = False,
        supports_chat_completions: bool = False,
        tool_prompt_role: str = "developer",
        transport: JsonTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("provider base URL is required")
        fields = request_fields or CustomRequestFields()
        resolved_response_fields = response_fields or CustomResponseFields()
        if not resolved_response_fields.content.strip():
            raise ProviderError("custom response content field is invalid")
        if not resolved_response_fields.thinking.strip():
            raise ProviderError("custom response thinking field is invalid")
        if fields.reasoning_effort is not None and not fields.reasoning_effort.strip():
            raise ProviderError("custom reasoning effort field is invalid")
        for field_name in (
            fields.temperature,
            fields.max_response_tokens,
            fields.max_output_tokens,
            fields.max_tokens,
            fields.response_format,
        ):
            if field_name is not None and not field_name.strip():
                raise ProviderError("custom request field is invalid")
        self._client = _CustomServiceClient(
            base_url=base_url,
            token=api_key,
            model=model,
            fields=fields,
            response_fields=resolved_response_fields,
            reasoning_effort=reasoning_effort,
            temperature=temperature,
            max_response_tokens=max_response_tokens,
            max_output_tokens=max_output_tokens,
            max_tokens=max_tokens,
            response_format=response_format,
            supports_tools=supports_tools,
            supports_chat_completions=supports_chat_completions,
            tool_prompt_role=_resolve_tool_prompt_role(tool_prompt_role),
            transport=transport or UrllibJsonTransport(),
        )

    def list_models(self) -> tuple[str, ...]:
        """Return model IDs exposed by the custom proxy."""
        return self._client.list_models()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        tools: Sequence[ToolDefinition] = (),
        model: str | None = None,
    ) -> ModelResponse:
        return self._client.complete(messages=messages, tools=tools, model=model)

    def embed(
        self,
        contents: Sequence[str],
        *,
        model: str | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        """Return one embedding vector for each supplied content string."""
        return self._client.embed(contents=contents, model=model)

    def complete_stream(self, **_kwargs: object) -> object:
        """Reserve the streaming surface until the proxy exposes its contract."""
        raise ProviderError("custom provider chat streaming is not available")


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
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        max_completion_tokens: int | None = None,
        max_output_tokens: int | None = None,
        max_tokens: int | None = None,
        response_format: str | None = None,
        supports_tools: bool = True,
        supports_chat_completions: bool = True,
        tool_prompt_role: str = "developer",
    ) -> None:
        if model is not None and not model.strip():
            raise ProviderError("provider model is required")
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._temperature = temperature
        self._max_completion_tokens = max_completion_tokens
        self._max_output_tokens = max_output_tokens
        self._max_tokens = max_tokens
        self._response_format = response_format
        self._supports_tools = supports_tools
        self._supports_chat_completions = supports_chat_completions
        self._tool_prompt_role: ToolPromptRole = _resolve_tool_prompt_role(
            tool_prompt_role
        )
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
            "messages": (
                [_serialize_message(message) for message in messages]
                if self._supports_tools
                else _serialize_custom_messages(
                    messages, tools, role=self._tool_prompt_role
                )
            ),
        }
        if tools and self._supports_tools:
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
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        if self._temperature is not None:
            payload["temperature"] = self._temperature
        if self._max_completion_tokens is not None:
            payload["max_completion_tokens"] = self._max_completion_tokens
        if self._max_output_tokens is not None:
            payload["max_output_tokens"] = self._max_output_tokens
        if self._max_tokens is not None:
            payload["max_tokens"] = self._max_tokens
        if self._response_format is not None:
            payload["response_format"] = {"type": self._response_format}

        try:
            result = self._transport.post(
                _chat_url(self._base_url, self._supports_chat_completions),
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
        headers["User-Agent"] = PEON_USER_AGENT
        if content_type:
            headers["Content-Type"] = "application/json"
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


class _CustomServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        model: str | None,
        fields: CustomRequestFields,
        response_fields: CustomResponseFields,
        reasoning_effort: str | None,
        temperature: float | None,
        max_response_tokens: int | None,
        max_output_tokens: int | None,
        max_tokens: int | None,
        response_format: str | None,
        supports_tools: bool,
        supports_chat_completions: bool,
        tool_prompt_role: ToolPromptRole,
        transport: JsonTransport,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._model = model
        self._fields = fields
        self._response_fields = response_fields
        self._reasoning_effort = reasoning_effort
        self._temperature = temperature
        self._max_response_tokens = max_response_tokens
        self._max_output_tokens = max_output_tokens
        self._max_tokens = max_tokens
        self._response_format = response_format
        self._supports_tools = supports_tools
        self._supports_chat_completions = supports_chat_completions
        self._tool_prompt_role: ToolPromptRole = _resolve_tool_prompt_role(
            tool_prompt_role
        )
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
        payload: dict[str, object] = {
            "version": 1,
            "service": "chat",
            "timestamp": int(time.time()),
            "messages": (
                [_serialize_message(message) for message in messages]
                if self._supports_tools
                else _serialize_custom_messages(
                    messages, tools, role=self._tool_prompt_role
                )
            ),
        }
        if tools and self._supports_tools:
            payload["tools"] = [_serialize_tool_definition(tool) for tool in tools]
        selected_model = model or self._model
        if selected_model:
            payload["model"] = selected_model
        self._add_optional_chat_fields(payload)

        result = self._post(payload, chat=True)
        thinking = _extract_custom_thinking(result, self._response_fields.thinking)
        completion = _extract_response_field(result, self._response_fields.content)
        usage = _parse_usage(result.get("usage"))
        if isinstance(completion, str) and completion.strip():
            tool_call = _parse_text_tool_call(completion)
            if tool_call is not None:
                return ModelResponse(
                    tool_call=tool_call,
                    thinking=thinking,
                    usage=usage,
                )
            final = _parse_text_final(completion)
            if final is not None:
                return ModelResponse(
                    content=final,
                    thinking=thinking,
                    usage=usage,
                )
            return ModelResponse(content=completion, thinking=thinking, usage=usage)
        if "choices" in result:
            return _parse_response(result)
        raise ProviderError("provider response did not contain completion")

    def embed(
        self,
        *,
        contents: Sequence[str],
        model: str | None,
    ) -> tuple[tuple[float, ...], ...]:
        payload: dict[str, object] = {
            "version": 1,
            "service": "embedding",
            "timestamp": int(time.time()),
            "contents": list(contents),
        }
        selected_model = model or self._model
        if selected_model:
            payload["model"] = selected_model

        result = self._post(payload)
        raw_embedding = result.get("embedding")
        if not isinstance(raw_embedding, list):
            raise ProviderError("provider response did not contain embedding")
        embeddings: list[tuple[float, ...]] = []
        for vector in raw_embedding:
            if not isinstance(vector, list):
                raise ProviderError("provider response contained an invalid embedding")
            if not all(
                isinstance(value, (int, float)) and not isinstance(value, bool)
                for value in vector
            ):
                raise ProviderError("provider response contained an invalid embedding value")
            embeddings.append(tuple(float(value) for value in vector))
        return tuple(embeddings)

    def _add_optional_chat_fields(self, payload: dict[str, object]) -> None:
        if self._fields.reasoning_effort and self._reasoning_effort is not None:
            payload[self._fields.reasoning_effort] = self._reasoning_effort
        if self._fields.temperature and self._temperature is not None:
            payload[self._fields.temperature] = self._temperature
        if self._fields.max_response_tokens and self._max_response_tokens is not None:
            payload[self._fields.max_response_tokens] = self._max_response_tokens
        if self._fields.max_output_tokens and self._max_output_tokens is not None:
            payload[self._fields.max_output_tokens] = self._max_output_tokens
        if self._fields.max_tokens and self._max_tokens is not None:
            payload[self._fields.max_tokens] = self._max_tokens
        if self._fields.response_format and self._response_format is not None:
            payload[self._fields.response_format] = self._response_format

    def _post(self, payload: JsonObject, *, chat: bool = False) -> JsonObject:
        try:
            result = self._transport.post(
                _chat_url(self._base_url, chat and self._supports_chat_completions),
                self._headers(),
                payload,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("provider request failed") from error
        if not isinstance(result, Mapping):
            raise ProviderError("provider response must be a JSON object")
        return result

    def _headers(self, *, content_type: bool = True) -> dict[str, str]:
        headers: dict[str, str] = {}
        headers["User-Agent"] = PEON_USER_AGENT
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


def _serialize_tool_definition(tool: ToolDefinition) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _chat_url(base_url: str, append_chat_completions: bool) -> str:
    if not append_chat_completions or base_url.endswith("/chat/completions"):
        return base_url
    return f"{base_url}/chat/completions"


def _extract_response_field(result: JsonObject, path: str) -> object:
    current: object = result
    for segment in path.split("."):
        key, separator, remainder = segment.partition("[")
        if key:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        while separator:
            index_text, closing, tail = remainder.partition("]")
            if not closing or not index_text.isdigit() or not isinstance(current, list):
                return None
            index = int(index_text)
            if not 0 <= index < len(current):
                return None
            current = current[index]
            if not tail:
                break
            if not tail.startswith("["):
                return None
            separator = "["
            remainder = tail[1:]
    return current


def _resolve_tool_prompt_role(role: str) -> ToolPromptRole:
    normalized = role.strip().lower()
    if normalized not in {"system", "developer"}:
        raise ProviderError("tool prompt role must be system or developer")
    return cast(ToolPromptRole, normalized)


def _serialize_custom_messages(
    messages: Sequence[AgentMessage],
    tools: Sequence[ToolDefinition],
    *,
    role: ToolPromptRole = "developer",
) -> list[dict[str, object]]:
    serialized: list[dict[str, object]] = []
    for message in messages:
        content = message.content
        if message.tool_call is not None:
            content = json.dumps(
                {
                    "tool_call": {
                        "name": message.tool_call.name,
                        "arguments": dict(message.tool_call.arguments),
                        **(
                            {"id": message.tool_call.call_id}
                            if message.tool_call.call_id is not None
                            else {}
                        ),
                    }
                },
                separators=(",", ":"),
            )
        serialized.append({"role": message.role, "content": content})
    if tools:
        serialized.append(
            {
                "role": role,
                "content": _build_tool_prompt_content(tools),
            }
        )
    return serialized


def _build_tool_prompt_content(tools: Sequence[ToolDefinition]) -> str:
    tool_specs = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        }
        for tool in tools
    ]
    return (
        "Peon provided callable tools through the tools field. "
        "When the next step requires using a tool, respond with only compact JSON "
        'in this exact shape: {"tool_call":{"name":"tool_name","arguments":{...}}}. '
        "Use only listed tool names and arguments that match their schemas. "
        "Use only one tool call per response. "
        'When no tool is needed, respond with only: {"final":"answer text"}. '
        "Available tools: " + json.dumps(tool_specs, ensure_ascii=False)
    )


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
    thinking = _extract_thinking(message)
    content = message.get("content")
    usage = _parse_usage(result.get("usage"))
    if tool_call is not None:
        return ModelResponse(
            content=content if isinstance(content, str) else "",
            thinking=thinking,
            tool_call=tool_call,
            usage=usage,
        )
    if isinstance(content, str) and content.strip():
        fallback_tool_call = _parse_text_tool_call(content)
        if fallback_tool_call is not None:
            return ModelResponse(
                tool_call=fallback_tool_call,
                thinking=thinking,
                usage=usage,
            )
        fallback_final = _parse_text_final(content)
        if fallback_final is not None:
            return ModelResponse(
                content=fallback_final,
                thinking=thinking,
                usage=usage,
            )
        return ModelResponse(content=content, thinking=thinking, usage=usage)
    raise ProviderError("provider response did not contain text or a tool call")


def _extract_thinking(message: Mapping[str, object]) -> str:
    for key in ("reasoning_content", "thinking", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _parse_usage(value: object) -> Usage | None:
    if not isinstance(value, Mapping):
        return None
    usage = Usage(
        input_tokens=_optional_int(value.get("prompt_tokens")),
        output_tokens=_optional_int(value.get("completion_tokens")),
        cache_tokens=_optional_int(
            _nested_value(value, "prompt_tokens_details", "cached_tokens")
        ),
        cost=_optional_float(value.get("cost")),
        currency=(
            value["currency"]
            if isinstance(value.get("currency"), str)
            and value["currency"].strip()
            else None
        ),
    )
    if usage == Usage():
        return None
    return usage


def _nested_value(value: Mapping[str, object], key: str, nested_key: str) -> object:
    nested = value.get(key)
    if not isinstance(nested, Mapping):
        return None
    return nested.get(nested_key)


def _optional_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _optional_float(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _extract_custom_thinking(result: JsonObject, path: str) -> str:
    configured = _extract_response_field(result, path)
    if isinstance(configured, str) and configured.strip():
        return configured
    return _extract_thinking(result)


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


def _parse_text_tool_call(content: str) -> ToolCall | None:
    try:
        raw_response = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_response, Mapping):
        return None

    raw_call = raw_response.get("tool_call")
    if raw_call is None and "tool_calls" in raw_response:
        raw_calls = raw_response.get("tool_calls")
        if not isinstance(raw_calls, list) or not raw_calls:
            raise ProviderError("provider response contained invalid tool calls")
        raw_call = raw_calls[0]
    if raw_call is None:
        return None
    if not isinstance(raw_call, Mapping):
        raise ProviderError("provider response contained an invalid tool call")

    name = raw_call.get("name")
    arguments = raw_call.get("arguments", {})
    if not isinstance(name, str) or not name.strip():
        raise ProviderError("provider tool call did not contain a name")
    if not isinstance(arguments, Mapping):
        raise ProviderError(
            "provider response tool call arguments must be an object"
        )
    call_id = raw_call.get("id", raw_call.get("call_id"))
    if call_id is not None and not isinstance(call_id, str):
        raise ProviderError("provider tool call id must be a string")
    return ToolCall(name=name, arguments=arguments, call_id=call_id)


def _parse_text_final(content: str) -> str | None:
    try:
        raw_response = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_response, Mapping) or "final" not in raw_response:
        return None
    final = raw_response["final"]
    if not isinstance(final, str):
        raise ProviderError("provider response final must be a string")
    return final