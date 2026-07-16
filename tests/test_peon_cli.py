from dataclasses import dataclass
from io import StringIO
from typing import Sequence

from peon.agent import AgentMessage, ModelResponse
from peon.app import ProviderConfig, main


@dataclass
class FakeProvider:
    response: str
    received_messages: tuple[AgentMessage, ...] = ()

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        return ModelResponse(content=self.response)


def test_command_runs_task_through_injected_provider_factory() -> None:
    provider = FakeProvider(response="Repository summarized.")
    configurations: list[ProviderConfig] = []

    def provider_factory(config: ProviderConfig) -> FakeProvider:
        configurations.append(config)
        return provider

    output = StringIO()
    error = StringIO()

    result = main(
        ["Summarize the repository.", "--provider", "fake", "--model", "small"],
        provider_factory=provider_factory,
        output=output,
        error=error,
    )

    assert result == 0
    assert output.getvalue() == "Repository summarized.\n"
    assert error.getvalue() == ""
    assert configurations == [ProviderConfig(name="fake", model="small")]
    assert provider.received_messages == (
        AgentMessage(role="user", content="Summarize the repository."),
    )


def test_command_reports_missing_task_without_traceback() -> None:
    error = StringIO()

    result = main([], error=error)

    assert result == 1
    assert "task is required" in error.getvalue()


def test_command_reports_missing_provider_without_traceback() -> None:
    error = StringIO()

    result = main(["Do work."], error=error)

    assert result == 1
    assert "provider is not configured" in error.getvalue()