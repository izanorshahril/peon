import sys
from typing import cast
import pytest

from peon.app.config import JsonProviderConfigStore, ProviderConfig
from peon.app.session_controller import (
    CommandErrorOutcome,
    ContinuationResponseIntent,
    LogoutIntent,
    LogoutOptionsOutcome,
    LogoutSuccessOutcome,
    ModelOption,
    ModelOptionsOutcome,
    ModelSelectIntent,
    ProviderSetupIntent,
    ProviderSetupStepOutcome,
    ProviderSuccessOutcome,
    SessionController,
    SettingOption,
    SettingsIntent,
    SettingsOptionsOutcome,
    SettingsUpdatedOutcome,
)
from peon.app.sessions import MemorySessionStore


class FakeModelProvider:
    def complete(self, *, messages: object, tools: object = (), model: str | None = None) -> object:
        from peon.agent import ModelResponse
        return ModelResponse(content="ok")


def test_controller_has_no_cli_imports() -> None:
    """Verify session_controller does not import peon.app.cli."""
    import peon.app.session_controller as sc
    for attr in dir(sc):
        val = getattr(sc, attr)
        if hasattr(val, "__module__") and getattr(val, "__module__", "").endswith(".cli"):
            pytest.fail(f"session_controller imports {attr} from cli module")


def test_provider_setup_openai_compatible_flow(tmp_path: object) -> None:
    config_path = tmp_path / "providers.json"  # type: ignore[operator]
    config_store = JsonProviderConfigStore(config_path)

    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )

    # Step 1: Start setup
    step1 = controller.dispatch_provider_setup(config_store=config_store)
    assert isinstance(step1, ProviderSetupStepOutcome)
    assert step1.step == "provider_type"
    assert not step1.is_secret
    token1 = step1.continuation_token

    # Step 2: Select openai-compatible
    step2 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token1, response="1")
    )
    assert isinstance(step2, ProviderSetupStepOutcome)
    assert step2.step == "base_url"
    token2 = step2.continuation_token

    # Step 3: Enter base URL
    step3 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token2, response="https://api.openai.com/v1")
    )
    assert isinstance(step3, ProviderSetupStepOutcome)
    assert step3.step == "api_key"
    assert step3.is_secret
    token3 = step3.continuation_token

    # Step 4: Enter API Key
    step4 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token3, response="sk-secret123")
    )
    assert isinstance(step4, ProviderSetupStepOutcome)
    assert step4.step == "model"
    token4 = step4.continuation_token

    # Step 5: Enter Model Name
    res = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token4, response="gpt-4o")
    )
    assert isinstance(res, ProviderSuccessOutcome)
    assert res.provider_name == "openai-compatible"
    assert res.model_name == "gpt-4o"

    # Verify persisted in config_store
    saved = config_store.load_all()
    assert len(saved) == 1
    assert saved[0].name == "openai-compatible"
    assert saved[0].api_key == "sk-secret123"


def test_provider_setup_github_copilot_flow(tmp_path: object) -> None:
    config_path = tmp_path / "providers.json"  # type: ignore[operator]
    config_store = JsonProviderConfigStore(config_path)

    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )

    step1 = controller.dispatch_provider_setup(config_store=config_store)
    token1 = step1.continuation_token

    step2 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token1, response="3")
    )
    assert isinstance(step2, ProviderSetupStepOutcome)
    assert step2.step == "copilot_token"
    assert step2.is_secret
    token2 = step2.continuation_token

    res = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token2, response="copilot-secret-token")
    )
    assert isinstance(res, ProviderSuccessOutcome)
    assert res.provider_name == "github-copilot"
    assert res.model_name == "gpt-4o"


def test_continuation_tokens_are_single_use() -> None:
    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )
    step1 = controller.dispatch_provider_setup()
    token = step1.continuation_token

    # First consumption succeeds
    res1 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token, response="1")
    )
    assert isinstance(res1, ProviderSetupStepOutcome)

    # Replaying token fails
    res2 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token, response="1")
    )
    assert isinstance(res2, CommandErrorOutcome)
    assert "invalid, expired, or already used" in res2.error


def test_model_select_dispatch(tmp_path: object) -> None:
    config_path = tmp_path / "providers.json"  # type: ignore[operator]
    config_store = JsonProviderConfigStore(config_path)
    config_store.save(
        ProviderConfig(name="openai", models=("gpt-4o", "gpt-4o-mini"), model="gpt-4o")
    )

    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )

    # List options
    outcome1 = controller.dispatch_model_select(config_store=config_store)
    assert isinstance(outcome1, ModelOptionsOutcome)
    assert len(outcome1.options) == 2
    assert outcome1.continuation_token is not None

    # Select target model directly
    outcome2 = controller.dispatch_model_select(
        ModelSelectIntent(target="gpt-4o-mini"), config_store=config_store
    )
    assert isinstance(outcome2, ModelOptionsOutcome)
    assert outcome2.updated
    assert outcome2.current_model == "gpt-4o-mini"


def test_settings_inspect_and_update() -> None:
    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )

    # Inspect
    inspect_res = controller.dispatch_settings()
    assert isinstance(inspect_res, SettingsOptionsOutcome)
    assert len(inspect_res.settings) >= 3

    # Update hide_thinking
    update_res = controller.dispatch_settings(
        SettingsIntent(setting="hide_thinking", value="true")
    )
    assert isinstance(update_res, SettingsUpdatedOutcome)
    assert update_res.setting == "hide_thinking"
    assert update_res.value == "True"

    # Update reasoning_effort
    reasoning_res = controller.dispatch_settings(
        SettingsIntent(setting="reasoning_effort", value="high")
    )
    assert isinstance(reasoning_res, SettingsUpdatedOutcome)
    assert reasoning_res.value == "high"


def test_logout_dispatch(tmp_path: object) -> None:
    config_path = tmp_path / "providers.json"  # type: ignore[operator]
    config_store = JsonProviderConfigStore(config_path)
    cfg1 = ProviderConfig(name="p1", models=("m1",))
    cfg2 = ProviderConfig(name="p2", models=("m2",))
    config_store.save(cfg1)
    config_store.save(cfg2)

    controller = SessionController(
        provider=FakeModelProvider(),
        session_store=MemorySessionStore(),
        session_id="test-session",
    )

    # List providers to logout
    res1 = controller.dispatch_logout(config_store=config_store)
    assert isinstance(res1, LogoutOptionsOutcome)
    assert len(res1.options) == 2
    token = res1.continuation_token

    # Remove via continuation
    res2 = controller.dispatch_continuation_response(
        ContinuationResponseIntent(continuation_token=token, response="1")
    )
    assert isinstance(res2, LogoutSuccessOutcome)
    assert res2.removed_provider_name == "p1"

    # Direct target removal
    res3 = controller.dispatch_logout(
        LogoutIntent(target="p2"), config_store=config_store
    )
    assert isinstance(res3, LogoutSuccessOutcome)
    assert res3.removed_provider_name == "p2"

    assert len(config_store.load_all()) == 0
