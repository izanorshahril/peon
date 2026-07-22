"""Built-in host identities and startup availability."""

from dataclasses import dataclass
from typing import Literal

HostRole = Literal["print", "events", "interactive", "embedded"]


class HostUnavailableError(Exception):
    """Raised when a requested host cannot be started."""


@dataclass(frozen=True, slots=True)
class Host:
    identifier: str
    role: HostRole
    available: bool = True


_BUILTIN_HOSTS = {
    host.identifier: host
    for host in (
        Host("print", "print"),
        Host("jsonl", "events"),
        Host("textual", "interactive"),
        Host("prompt-toolkit", "interactive"),
        Host("embedded", "embedded"),
        Host("fullscreen", "interactive", available=False),
        Host("webapp", "interactive", available=False),
    )
}


def resolve_host(identifier: str) -> Host:
    """Resolve a stable built-in host identifier before startup work."""
    if identifier == "prompt-toolkit":
        raise HostUnavailableError(
            "prompt-toolkit host has been retired; use 'textual' for interactive mode"
        )
    if identifier == "textual":
        try:
            import textual  # noqa: F401
        except ImportError as caught:
            raise HostUnavailableError(
                "Interactive TUI requires the 'tui' optional extra. "
                "Install with: pip install \"peon[tui]\" or uv add \"peon[tui]\""
            ) from caught
    host = _BUILTIN_HOSTS.get(identifier)
    if host is None:
        raise HostUnavailableError(f"unknown host '{identifier}'")
    if not host.available:
        raise HostUnavailableError(f"{identifier} host is not available yet")
    return host