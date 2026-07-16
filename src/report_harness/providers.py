"""Provider adapters with one normalized justification surface."""

import base64
import json
import os
from typing import Any, Callable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import ProviderError
from .models import ProviderRequest, ProviderResponse


class JsonTransport(Protocol):
    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]: ...


class UrllibJsonTransport:
    """Small JSON POST transport used when no test or application transport is supplied."""

    def post(
        self,
        url: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError) as error:
            raise ProviderError(f"Provider request failed: {url}") from error
        if not isinstance(result, Mapping):
            raise ProviderError("Provider returned a non-object response")
        return result


class OpenAICompatibleProvider:
    """Use an OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        transport: JsonTransport | None = None,
    ) -> None:
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=api_key,
            model=model,
            transport=transport or UrllibJsonTransport(),
        )

    def justify(self, request: ProviderRequest) -> ProviderResponse:
        return self._client.justify(request)


class GitHubCopilotProvider:
    """Use the GitHub Copilot chat-completions endpoint with login credentials."""

    def __init__(
        self,
        token: str | None = None,
        model: str = "gpt-4o",
        base_url: str = "https://api.githubcopilot.com",
        transport: JsonTransport | None = None,
        token_provider: Callable[[], str] | None = None,
    ) -> None:
        resolved_token = token or (token_provider() if token_provider else None)
        resolved_token = resolved_token or os.environ.get("GITHUB_COPILOT_TOKEN")
        if not resolved_token:
            raise ProviderError(
                "GitHub Copilot login token is not configured; provide a token "
                "or GITHUB_COPILOT_TOKEN"
            )
        self._client = _ChatCompletionsClient(
            base_url=base_url,
            token=resolved_token,
            model=model,
            transport=transport or UrllibJsonTransport(),
        )

    def justify(self, request: ProviderRequest) -> ProviderResponse:
        return self._client.justify(request)


class _ChatCompletionsClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        model: str,
        transport: JsonTransport,
    ) -> None:
        if not base_url.strip():
            raise ProviderError("Provider base URL is required")
        if not token.strip():
            raise ProviderError("Provider token is required")
        if not model.strip():
            raise ProviderError("Provider model is required")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.model = model
        self.transport = transport

    def justify(self, request: ProviderRequest) -> ProviderResponse:
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only a JSON object with string fields "
                        "answer and justification."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": request.instructions
                            or "Interpret the supplied image evidence.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": self._image_data_url(request),
                            },
                        },
                    ],
                },
            ],
        }
        try:
            result = self.transport.post(
                f"{self.base_url}/chat/completions",
                {
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                payload,
            )
        except ProviderError:
            raise
        except Exception as error:
            raise ProviderError("Provider request failed") from error
        return self._parse_response(result)

    @staticmethod
    def _image_data_url(request: ProviderRequest) -> str:
        encoded = base64.b64encode(request.evidence.content).decode("ascii")
        return f"data:{request.evidence.media_type};base64,{encoded}"

    @staticmethod
    def _parse_response(result: Mapping[str, Any]) -> ProviderResponse:
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ProviderError(
                "Provider response did not contain a chat message"
            ) from error
        if isinstance(content, list):
            content = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, Mapping)
            )
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError as error:
                raise ProviderError(
                    "Provider response must contain JSON with answer and justification"
                ) from error
        if not isinstance(content, Mapping):
            raise ProviderError(
                "Provider response must contain JSON with answer and justification"
            )
        answer = content.get("answer")
        justification = content.get("justification")
        if not isinstance(answer, str) or not isinstance(justification, str):
            raise ProviderError(
                "Provider response must contain string answer and justification"
            )
        return ProviderResponse(answer=answer, justification=justification)
