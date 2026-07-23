import time
from typing import Any, Mapping
import pytest

from peon.agent import (
    AgentContext,
    ModelProvider,
    ModelResponse,
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    Usage,
)
from peon.agent.runtime_errors import LimitExceededError
from peon.app.coding_session import CodingSession, RunLimits, TurnResult
from peon.app.config import (
    CAPABILITY_PROFILES,
    FilteredToolExecutor,
    UiConfig,
    active_capability_profile,
    filter_enabled_tools,
    filter_tool_executor,
    set_capability_profile,
)
from peon.app.sessions import MemorySessionStore
from peon.embedded import EmbeddedSession


class FakeToolExecutor:
    def __init__(self, tools: tuple[ToolDefinition, ...]) -> None:
        self._tools = tools
        self.invocations: list[tuple[str, Mapping[str, object]]] = []

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return self._tools

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        self.invocations.append((name, arguments))
        return f"result of {name}"


class FakeModelProvider:
    def __init__(self, responses: list[ModelResponse] | None = None) -> None:
        self.responses = responses or [ModelResponse(content="default response")]
        self.call_count = 0

    def complete(self, *, messages: object, tools: object = (), model: str | None = None) -> ModelResponse:
        idx = min(self.call_count, len(self.responses) - 1)
        self.call_count += 1
        return self.responses[idx]


def test_capability_profiles_filter_tools() -> None:
    all_tools = (
        ToolDefinition("read", "Read file", {}),
        ToolDefinition("write", "Write file", {}),
        ToolDefinition("edit", "Edit file", {}),
        ToolDefinition("bash", "Bash command", {}),
        ToolDefinition("list", "List dir", {}),
        ToolDefinition("unknown", "Unknown tool", {}),
    )
    executor = FakeToolExecutor(all_tools)

    # none profile
    cfg_none = set_capability_profile(UiConfig(), "none")
    filtered_none = filter_tool_executor(cfg_none, executor)
    assert len(filtered_none.tools) == 0

    # read-only profile
    cfg_ro = set_capability_profile(UiConfig(), "read-only")
    filtered_ro = filter_tool_executor(cfg_ro, executor)
    tool_names_ro = [t.name for t in filtered_ro.tools]
    assert "read" in tool_names_ro
    assert "list" in tool_names_ro
    assert "write" not in tool_names_ro
    assert "bash" not in tool_names_ro

    # coding profile
    cfg_coding = set_capability_profile(UiConfig(), "coding")
    filtered_coding = filter_tool_executor(cfg_coding, executor)
    tool_names_coding = [t.name for t in filtered_coding.tools]
    assert "read" in tool_names_coding
    assert "write" in tool_names_coding
    assert "edit" in tool_names_coding
    assert "bash" in tool_names_coding
    assert "unknown" not in tool_names_coding


def test_disabled_forged_tool_call_fails_before_execution() -> None:
    all_tools = (ToolDefinition("read", "Read", {}), ToolDefinition("write", "Write", {}))
    executor = FakeToolExecutor(all_tools)
    cfg = UiConfig(enabled_tools=("read",))
    filtered = filter_tool_executor(cfg, executor)

    # Attempting to invoke disabled tool 'write' raises ValueError
    with pytest.raises(ValueError, match="tool 'write' is disabled"):
        filtered.invoke("write", {})

    assert len(executor.invocations) == 0


def test_embedded_session_defaults_to_no_tools() -> None:
    provider = FakeModelProvider([ModelResponse(content="hello")])
    session = EmbeddedSession(provider=provider)
    res = session.submit("test prompt")
    assert res.status == "success"
    assert res.content == "hello"


def test_run_limits_max_cost_and_currency_mismatch() -> None:
    store = MemorySessionStore()
    session_id = store.create().session_id
    provider = FakeModelProvider([
        ModelResponse(
            content="res1",
            usage=Usage(input_tokens=10, output_tokens=10, cost=1.5, currency="USD"),
        )
    ])
    session = CodingSession(
        provider=provider,
        session_store=store,
        session_id=session_id,
        run_id="r1",
        limits=RunLimits(max_cost=1.0, currency="USD"),
    )
    res = session.prompt("test prompt")
    assert res.status == "error"
    assert res.stop_reason == "max_cost_exceeded"

    # Currency mismatch
    store2 = MemorySessionStore()
    session_id2 = store2.create().session_id
    provider2 = FakeModelProvider([
        ModelResponse(
            content="res2",
            usage=Usage(input_tokens=10, output_tokens=10, cost=0.5, currency="EUR"),
        )
    ])
    session2 = CodingSession(
        provider=provider2,
        session_store=store2,
        session_id=session_id2,
        run_id="r2",
        limits=RunLimits(max_cost=1.0, currency="USD"),
    )
    res2 = session2.prompt("test prompt")
    assert res2.status == "error"
    assert res2.stop_reason == "currency_mismatch"


def test_run_limits_missing_usage_raises_accounting_unavailable() -> None:
    store = MemorySessionStore()
    session_id = store.create().session_id
    provider = FakeModelProvider([ModelResponse(content="res", usage=None)])
    session = CodingSession(
        provider=provider,
        session_store=store,
        session_id=session_id,
        run_id="r1",
        limits=RunLimits(max_total_tokens=100),
    )
    res = session.prompt("test prompt")
    assert res.status == "error"
    assert res.stop_reason == "token_limit_accounting_unavailable"


def test_default_cli_registry_absent_sample_tools() -> None:
    from peon.app.cli import ExtensionRegistry, register_filesystem_tools
    reg = ExtensionRegistry()
    register_filesystem_tools(reg)
    tool_names = [t.name for t in reg.tools]
    assert "read" in tool_names
    assert "write" in tool_names
    assert "edit" in tool_names
    assert "bash" in tool_names
    assert "word_count" not in tool_names


def test_run_limits_max_provider_calls_exceeded() -> None:
    store = MemorySessionStore()
    session_id = store.create().session_id
    provider = FakeModelProvider([
        ModelResponse(
            tool_call=ToolCall(name="read", arguments={}, call_id="call-1")
        ),
        ModelResponse(content="done"),
    ])
    all_tools = (ToolDefinition("read", "Read", {}),)
    executor = FakeToolExecutor(all_tools)
    session = CodingSession(
        provider=provider,
        session_store=store,
        session_id=session_id,
        run_id="r1",
        executor=executor,
        limits=RunLimits(max_provider_calls=1),
    )
    res = session.prompt("test prompt")
    assert res.status == "error"
    assert res.stop_reason == "max_provider_calls_exceeded"
