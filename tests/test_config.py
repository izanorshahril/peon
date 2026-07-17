from peon.app import JsonProviderConfigStore, ProviderConfig


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
