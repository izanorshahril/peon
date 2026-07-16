"""The minimal one-turn agent orchestration boundary."""

from .errors import AgentError
from .models import AgentContext, AgentMessage
from .provider import ModelProvider


def run_task(
    task: str,
    provider: ModelProvider,
    *,
    context: AgentContext | None = None,
    model: str | None = None,
) -> str:
    """Run one task against an injected provider and return its response."""
    normalized_task = task.strip()
    if not normalized_task:
        raise AgentError("task is required")

    active_context = context or AgentContext()
    active_context.add(AgentMessage(role="user", content=normalized_task))
    try:
        response = provider.complete(
            messages=active_context.messages,
            model=model,
        )
    except Exception as error:
        raise AgentError(f"provider request failed: {error}") from error

    response_text = response.content.strip()
    if not response_text:
        raise AgentError("provider returned an empty response")

    active_context.add(AgentMessage(role="assistant", content=response_text))
    return response_text