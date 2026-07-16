import json

import pytest

from report_harness.errors import ProviderError
from report_harness.models import EvidenceEnvelope, ProviderRequest
from report_harness.providers import GitHubCopilotProvider, OpenAICompatibleProvider


class StubTransport:
    def __init__(self, response):
        self.response = response
        self.url = None
        self.headers = None
        self.payload = None

    def post(self, url, headers, payload):
        self.url = url
        self.headers = headers
        self.payload = payload
        return self.response


def provider_request() -> ProviderRequest:
    return ProviderRequest(
        row_number=7,
        evidence=EvidenceEnvelope(
            reference="evidence.png",
            media_type="image/png",
            content=b"image-bytes",
        ),
        instructions="Check whether the evidence passes.",
    )


def test_openai_compatible_provider_returns_normalized_response() -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "Pass",
                                "justification": "The evidence is sufficient.",
                            }
                        )
                    }
                }
            ]
        }
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1/",
        api_key="openai-key",
        model="vision-model",
        transport=transport,
    )

    response = provider.justify(provider_request())

    assert response.answer == "Pass"
    assert response.justification == "The evidence is sufficient."
    assert transport.url == "https://example.test/v1/chat/completions"
    assert transport.headers["Authorization"] == "Bearer openai-key"
    assert transport.payload["model"] == "vision-model"
    user_content = transport.payload["messages"][1]["content"]
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_github_copilot_provider_uses_the_same_normalized_surface() -> None:
    transport = StubTransport(
        {
            "choices": [
                {
                    "message": {
                        "content": '{"answer":"Review", "justification":"Visible evidence."}'
                    }
                }
            ]
        }
    )
    provider = GitHubCopilotProvider(
        token="copilot-token",
        model="gpt-4o",
        transport=transport,
    )

    response = provider.justify(provider_request())

    assert response.answer == "Review"
    assert response.justification == "Visible evidence."
    assert transport.headers["Authorization"] == "Bearer copilot-token"


def test_provider_rejects_unstructured_model_output() -> None:
    transport = StubTransport(
        {"choices": [{"message": {"content": "not-json"}}]}
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test",
        api_key="key",
        model="model",
        transport=transport,
    )

    with pytest.raises(ProviderError, match="answer and justification"):
        provider.justify(provider_request())


def test_github_copilot_provider_requires_login_credentials(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_COPILOT_TOKEN", raising=False)

    with pytest.raises(ProviderError, match="login token"):
        GitHubCopilotProvider()
