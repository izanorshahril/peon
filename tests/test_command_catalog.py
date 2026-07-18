from peon.app.commands import DEFAULT_COMMAND_CATALOG


def test_catalog_resolves_canonical_and_compatibility_names() -> None:
    assert DEFAULT_COMMAND_CATALOG.search("switch model")[0].command.id == "model"
    assert DEFAULT_COMMAND_CATALOG.search("reset")[0].command.id == "new"
    assert DEFAULT_COMMAND_CATALOG.search("/model")[0].command.name == "/model"

    invocation = DEFAULT_COMMAND_CATALOG.resolve("/clear")

    assert invocation is not None
    assert invocation.command.id == "new"
    assert invocation.argument == ""


def test_catalog_supports_migration_vocabulary() -> None:
    assert DEFAULT_COMMAND_CATALOG.search("connect")[0].command.id == "provider"
    assert DEFAULT_COMMAND_CATALOG.search("login")[0].command.id == "provider"
    assert DEFAULT_COMMAND_CATALOG.search("config")[0].command.id == "settings"


def test_catalog_normalizes_separators_and_marks_reserved_commands() -> None:
    matches = DEFAULT_COMMAND_CATALOG.search("SWITCH_model")

    assert matches[0].command.id == "model"
    assert matches[0].match_kind == "token-match"
    assert any(
        match.command.id == "compact" and match.is_reserved
        for match in DEFAULT_COMMAND_CATALOG.search("/")
    )


def test_catalog_hides_compatibility_commands_from_default_list() -> None:
    visible_names = {
        match.command.name for match in DEFAULT_COMMAND_CATALOG.search("/")
    }

    assert "/new" in visible_names
    assert "/models" not in visible_names
    assert "/temperature" not in visible_names

    hidden_match = DEFAULT_COMMAND_CATALOG.search(
        "/temperature", include_hidden=True
    )[0]
    assert hidden_match.command.availability == "hidden-compatibility"


def test_catalog_only_parses_arguments_after_direct_name_resolution() -> None:
    invocation = DEFAULT_COMMAND_CATALOG.resolve("/model beta")
    search_only_input = DEFAULT_COMMAND_CATALOG.resolve("/switch model")
    tabbed_invocation = DEFAULT_COMMAND_CATALOG.resolve("/model\tbeta")

    assert invocation is not None
    assert invocation.command.id == "model"
    assert invocation.argument == "beta"
    assert tabbed_invocation is not None
    assert tabbed_invocation.argument == "beta"
    assert search_only_input is None


def test_catalog_help_separates_available_and_reserved_commands() -> None:
    help_text = DEFAULT_COMMAND_CATALOG.help_text()

    assert help_text.index("Available commands:") < help_text.index(
        "Reserved commands:"
    )
    assert "/model     switch the active model" in help_text
    assert "/compact   compact conversation context" in help_text
    assert "(also: connect, login)" in help_text