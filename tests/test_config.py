import json
from collections.abc import Mapping

import pytest

from peon.app import JsonProviderConfigStore, ProviderConfig, UiConfig
from peon.app.cli import (
    provider_config_setting_specs,
    reasoning_effort_choices,
    update_provider_setting,
)
from peon.app.config import (
    filter_enabled_tools,
    filter_tool_executor,
    update_general_setting,
    update_shortcut_setting,
    update_tool_setting,
    update_ui_setting,
)
from peon.agent import ToolDefinition, ToolExecutionContext


def test_json_store_round_trips_multiple_profiles_and_active_provider(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    first = ProviderConfig(
        name="openai-compatible",
        model="local-model",
        models=("local-model", "other-model"),
        base_url="http://localhost:11434/v1",
    )
    second = ProviderConfig(
        name="github-copilot",
        model="gpt-4o",
        copilot_token="token",
    )

    store.save(first)
    store.save(second)

    assert store.load_all() == (first, second)
    assert store.load() == second


def test_legacy_openai_profile_enables_native_tools_by_default(tmp_path) -> None:
    path = tmp_path / "provider.json"
    path.write_text(
        json.dumps(
            {
                "providers": [{"name": "openai-compatible", "base_url": "http://localhost"}],
                "active": "openai-compatible|http://localhost",
            }
        ),
        encoding="utf-8",
    )

    config = JsonProviderConfigStore(path).load()

    assert config is not None
    assert config.supports_tools is True


def test_json_store_round_trips_custom_provider_settings(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    config = ProviderConfig(
        name="Corporate",
        provider_type="custom",
        model="chat-model",
        base_url="http://localhost:8080",
        reasoning_effort_field="reasoning_effort",
        reasoning_effort="high",
        temperature_field="temp",
        temperature=0.2,
        max_response_tokens_field="max_tokens",
        max_response_tokens=2048,
        response_format_field="response_format",
        response_format="json_object",
        response_thinking_field="analysis",
    )

    store.save(config)

    assert store.load() == config


def test_json_store_deleting_inactive_profile_preserves_active_provider(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    first = ProviderConfig(name="openai-compatible", base_url="http://first.test/v1")
    second = ProviderConfig(name="openai-compatible", base_url="http://second.test/v1")

    store.save(first)
    store.save(second)
    store.delete(first)

    assert store.load_all() == (second,)
    assert store.load() == second


def test_json_store_deleting_active_profile_selects_remaining_provider(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    first = ProviderConfig(name="openai-compatible", base_url="http://first.test/v1")
    second = ProviderConfig(name="github-copilot", model="gpt-4o")

    store.save(first)
    store.save(second)
    store.delete(second)

    assert store.load_all() == (first,)
    assert store.load() == first


def test_json_store_deleting_last_profile_removes_file(tmp_path) -> None:
    profile_path = tmp_path / "provider.json"
    store = JsonProviderConfigStore(profile_path)
    config = ProviderConfig(name="openai-compatible", base_url="http://first.test/v1")

    store.save(config)
    store.delete(config)

    assert not profile_path.exists()
    assert store.load_all() == ()


def test_json_store_round_trips_expanded_provider_and_ui_settings(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    provider = ProviderConfig(
        name="ST",
        provider_type="custom",
        base_url="https://proxy.test/v1",
        reasoning_effort=None,
        temperature=0.4,
        max_response_tokens=None,
        max_output_tokens=8192,
        max_tokens=16384,
        max_output_tokens_field="outputTokenLimit",
        max_tokens_field="tokenLimit",
        response_content_field="result.message",
        tool_prompt_role="system",
        supports_tools=True,
        supports_stream=True,
        supports_chat_completions=False,
    )
    ui = UiConfig(
        user_top_blank_lines=2,
        chat_area_color="#202020",
        assistant_message_color="#f0f0f0",
        tool_message_background="#282832",
        tool_output_color="#ffffff",
        command_selected_color="#00ff00",
        text_format="italic",
        hide_thinking=True,
        render_tool_markdown=True,
        session_list_delimiter=False,
        reasoning_shortcut="alt+r",
        thinking_shortcut="alt+t",
        tools_shortcut="alt+o",
    )

    store.save(provider)
    store.save_ui(ui)

    assert store.load() == provider
    assert store.load_ui() == ui
    assert store.load_ui().tool_output_color == "#ffffff"


def test_json_store_updates_provider_identity_without_duplicate(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    original = ProviderConfig(name="ST", base_url="https://old.test/v1")
    updated = ProviderConfig(name="ST Chat", base_url="https://new.test/v1")
    store.save(original)

    store.update(original, updated)

    assert store.load_all() == (updated,)
    assert store.load() == updated


def test_renaming_legacy_provider_preserves_adapter_type() -> None:
    config = ProviderConfig(
        name="openai-compatible",
        base_url="https://example.test/v1",
    )

    renamed = update_provider_setting(config, "name", "Local AI")

    assert renamed.name == "Local AI"
    assert renamed.provider_type == "openai-compatible"


def test_provider_setting_can_switch_tool_prompt_role() -> None:
    config = ProviderConfig(name="custom", provider_type="custom")

    updated = update_provider_setting(config, "tool-prompt-role", "system")

    assert updated.tool_prompt_role == "system"


def test_provider_setting_can_switch_custom_thinking_response_field() -> None:
    config = ProviderConfig(name="custom", provider_type="custom")

    updated = update_provider_setting(config, "response-thinking-field", "analysis")

    assert updated.response_thinking_field == "analysis"


def test_reasoning_capability_is_limited_to_openai_and_custom_profiles() -> None:
    openai = ProviderConfig(name="openai-compatible")
    custom = ProviderConfig(name="proxy", provider_type="custom")
    copilot = ProviderConfig(name="github-copilot")

    assert reasoning_effort_choices(openai) == ("none", "low", "medium", "high")
    assert reasoning_effort_choices(custom) == ("none", "low", "medium", "high")
    assert reasoning_effort_choices(copilot) == ()
    assert any(spec.key == "reasoning" for spec in provider_config_setting_specs(openai))
    assert any(spec.key == "reasoning" for spec in provider_config_setting_specs(custom))
    assert not any(spec.key == "reasoning" for spec in provider_config_setting_specs(copilot))


def test_none_reasoning_setting_omits_the_provider_value() -> None:
    config = ProviderConfig(name="openai-compatible", reasoning_effort="high")

    updated = update_provider_setting(config, "reasoning", "none")

    assert updated.reasoning_effort is None


def test_general_and_shortcut_settings_validate_and_update() -> None:
    config = UiConfig()

    hidden = update_general_setting(config, "hide-thinking", "true")
    markdown = update_general_setting(hidden, "render-tool-markdown", "true")
    system_italic = update_ui_setting(config, "system-text-format", "italic")
    no_delimiters = update_general_setting(
        markdown,
        "session-list-delimiter",
        "false",
    )
    updated = update_shortcut_setting(markdown, "tools", "Alt+O")

    assert updated.hide_thinking is True
    assert updated.render_tool_markdown is True
    assert system_italic.system_text_format == "italic"
    assert no_delimiters.session_list_delimiter is False
    assert updated.tools_shortcut == "alt+o"

    with pytest.raises(ValueError, match="reserved"):
        update_general_setting(config, "reserved-auto-compaction", "true")
    with pytest.raises(ValueError, match="blank"):
        update_shortcut_setting(config, "thinking", " ")
    with pytest.raises(ValueError, match="already assigned"):
        update_shortcut_setting(config, "thinking", config.tools_shortcut)


def test_tool_settings_update_and_filter_provider_definitions() -> None:
    config = UiConfig()
    tools = (
        ToolDefinition(name="read", description="Read", parameters={}),
        ToolDefinition(name="word_count", description="Count", parameters={}),
    )

    assert [tool.name for tool in filter_enabled_tools(config, tools)] == ["read"]
    enabled = update_tool_setting(config, "word_count", "true")
    assert enabled.enabled_tools == (*config.enabled_tools, "word_count")
    assert [tool.name for tool in filter_enabled_tools(enabled, tools)] == [
        "read",
        "word_count",
    ]
    disabled = update_tool_setting(enabled, "read", "false")
    assert [tool.name for tool in filter_enabled_tools(disabled, tools)] == [
        "word_count"
    ]

    filtered = filter_tool_executor(disabled, _ToolExecutor(tools))
    assert filtered.tools == (tools[1],)
    with pytest.raises(ValueError, match="disabled"):
        filtered.invoke("read", {})


def test_filtered_tool_executor_forwards_execution_context() -> None:
    config = UiConfig()
    tool = ToolDefinition(name="read", description="Read", parameters={})
    executor = _ContextualToolExecutor((tool,))
    filtered = filter_tool_executor(config, executor)
    execution_context = ToolExecutionContext()

    assert filtered.invoke_with_context("read", {}, execution_context) == "context"
    assert executor.received_context is execution_context


class _ToolExecutor:
    def __init__(self, tools: tuple[ToolDefinition, ...]) -> None:
        self._tools = tools

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return self._tools

    def invoke(self, name: str, arguments: Mapping[str, object]) -> str:
        del arguments
        return name


class _ContextualToolExecutor(_ToolExecutor):
    def __init__(self, tools: tuple[ToolDefinition, ...]) -> None:
        super().__init__(tools)
        self.received_context: ToolExecutionContext | None = None

    def invoke_with_context(
        self,
        name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> str:
        del name, arguments
        self.received_context = context
        return "context"


def test_json_store_keeps_ui_settings_after_last_provider_is_deleted(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    provider = ProviderConfig(name="openai-compatible", base_url="http://localhost/v1")
    ui = UiConfig(background_color="#202020")
    store.save(provider)
    store.save_ui(ui)

    store.delete(provider)

    assert store.load_all() == ()
    assert store.load_ui() == ui
