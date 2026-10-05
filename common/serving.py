"""The ports this process answers on.

A port setting is read once, by the server that binds it, and changing it afterwards moves
nothing until the next start. Anything addressing this running install asks here; the
setting would send it to a port nothing is listening on.
"""

from __future__ import annotations

import contextlib
import dataclasses
from pathlib import Path
from typing import Any, Literal

from common.config_access import NetworkConfig

Port = Literal["http_port", "ws_port", "theme_assets_port"]
_bound: dict[str, int] = {}


def bound(field: Port, port: int) -> None:
    """Record the port a server was started on, under its `NetworkConfig` field."""
    _bound[field] = int(port)


def bound_ports() -> set[int]:
    """The ports this process is listening on."""
    return set(_bound.values())


def network(config: Any) -> NetworkConfig:
    """The network settings as this process serves them: each port a server here was
    started on, and the setting for one nothing here has started."""
    configured = NetworkConfig.from_config(config)
    return dataclasses.replace(
        configured,
        http_port=_bound.get("http_port", configured.http_port),
        ws_port=_bound.get("ws_port", configured.ws_port),
        theme_assets_port=_bound.get("theme_assets_port", configured.theme_assets_port))


# Beside `.restart` in the config folder: the HTTP port this run bound, for a command run
# from a shell, which reads the setting and so looks where the next start would listen,
# not where this one does. Left behind by a run that was killed, which is harmless - what
# is found at that port is checked before it is believed.
PORT_FILE = ".http_port"


def publish(config_dir: Path) -> None:
    """Say which HTTP port this run is listening on."""
    port = _bound.get("http_port")
    if port is not None:
        (config_dir / PORT_FILE).write_text(f"{port}\n", encoding="utf-8")


def withdraw(config_dir: Path) -> None:
    """This run is no longer listening."""
    with contextlib.suppress(OSError):
        (config_dir / PORT_FILE).unlink()


def published(config_dir: Path) -> int | None:
    """The HTTP port a running instance of this config folder said it listens on."""
    try:
        return int((config_dir / PORT_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def forget() -> None:
    """Nothing has been bound. For a test that records a port."""
    _bound.clear()
