from dataclasses import dataclass
from typing import Sequence

from peon.agent import AgentContext, AgentMessage, ModelResponse, run_task
from peon.agent import AgentError


@dataclass
class FakeProvider:
    response: str
    received_messages: tuple[AgentMessage, ...] = ()
    received_model: str | None = None

    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        model: str | None = None,
    ) -> ModelResponse:
        self.received_messages = tuple(messages)
        self.received_model = model
        return ModelResponse(content=self.response)


class FailingProvider:
    def complete(
        self,
        *,
        messages: Sequence[AgentMessage],
        model: str | None = None,
    ) -> ModelResponse:
        raise RuntimeError("connection refused")


def test_run_task_forwards_compact_context_and_returns_final_response() -> None:
    provider = FakeProvider(response="Task complete.")
    context = AgentContext(
        messages=[AgentMessage(role="system", content="Be concise.")]
    )

    result = run_task(
        "Summarize the repository.",
        provider,
        context=context,
        model="fake-model",
    )

    assert result == "Task complete."
    assert provider.received_messages == (
        AgentMessage(role="system", content="Be concise."),
        AgentMessage(role="user", content="Summarize the repository."),
    )
    assert provider.received_model == "fake-model"
    assert context.messages[-1] == AgentMessage(
        role="assistant", content="Task complete."
    )


def test_run_task_exposes_provider_failure_as_agent_error() -> None:
    try:
        run_task("Do work.", FailingProvider())
    except AgentError as error:
        assert str(error) == "provider request failed: connection refused"
    else:
        raise AssertionError("run_task should report provider failures")