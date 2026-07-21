import pytest

from peon.app.hosts import HostUnavailableError, resolve_host


@pytest.mark.parametrize(
    ("host_id", "role"),
    [
        ("print", "print"),
        ("jsonl", "events"),
        ("textual", "interactive"),
        ("embedded", "embedded"),
    ],
)
def test_builtin_hosts_have_stable_ids_and_roles(
    host_id: str,
    role: str,
) -> None:
    host = resolve_host(host_id)

    assert host.identifier == host_id
    assert host.role == role
    assert host.available is True


def test_retired_prompt_toolkit_host_returns_actionable_error() -> None:
    with pytest.raises(HostUnavailableError, match="prompt-toolkit host has been retired"):
        resolve_host("prompt-toolkit")


@pytest.mark.parametrize("host_id", ["fullscreen", "webapp"])
def test_reserved_hosts_fail_before_startup(host_id: str) -> None:
    with pytest.raises(HostUnavailableError, match=f"{host_id} host is not available"):
        resolve_host(host_id)


def test_unknown_hosts_report_their_identifier() -> None:
    with pytest.raises(HostUnavailableError, match="unknown host 'robot'"):
        resolve_host("robot")