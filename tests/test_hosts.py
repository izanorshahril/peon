import pytest

from peon.app.hosts import HostUnavailableError, resolve_host


@pytest.mark.parametrize(
    ("host_id", "role"),
    [
        ("print", "print"),
        ("jsonl", "events"),
        ("textual", "interactive"),
        ("prompt-toolkit", "interactive"),
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


@pytest.mark.parametrize("host_id", ["fullscreen", "webapp"])
def test_reserved_hosts_fail_before_startup(host_id: str) -> None:
    with pytest.raises(HostUnavailableError, match=f"{host_id} host is not available"):
        resolve_host(host_id)


def test_unknown_hosts_report_their_identifier() -> None:
    with pytest.raises(HostUnavailableError, match="unknown host 'robot'"):
        resolve_host("robot")