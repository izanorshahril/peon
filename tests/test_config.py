from peon.app import JsonProviderConfigStore, ProviderConfig, UiConfig
from peon.app.cli import update_provider_setting


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
        supports_tools=True,
        supports_stream=True,
        supports_chat_completions=False,
    )
    ui = UiConfig(
        user_top_blank_lines=2,
        chat_area_color="#202020",
        assistant_message_color="#f0f0f0",
        command_selected_color="#00ff00",
        text_format="italic",
    )

    store.save(provider)
    store.save_ui(ui)

    assert store.load() == provider
    assert store.load_ui() == ui


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


def test_json_store_keeps_ui_settings_after_last_provider_is_deleted(tmp_path) -> None:
    store = JsonProviderConfigStore(tmp_path / "provider.json")
    provider = ProviderConfig(name="openai-compatible", base_url="http://localhost/v1")
    ui = UiConfig(background_color="#202020")
    store.save(provider)
    store.save_ui(ui)

    store.delete(provider)

    assert store.load_all() == ()
    assert store.load_ui() == ui
