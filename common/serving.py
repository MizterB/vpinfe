"""The ports this process answers on.

A port setting is read once, by the server that binds it, and changing it afterwards moves
nothing until the next start. Anything addressing this running install asks here; the
setting would send it to a port nothing is listening on.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from common import device_registry
from common.config_access import NetworkConfig

Port = Literal["http_port", "ws_port", "theme_assets_port"]
_bound: dict[str, int] = {}


def bound(field: Port, port: int) -> None:
    """Record the port a server was started on, under its `NetworkConfig` field."""
    _bound[field] = int(port)


def bound_port(field: Port) -> int | None:
    """The port this process started the named server on, or None where it has not."""
    return _bound.get(field)


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


def publish() -> None:
    """Say, on this install's row, which HTTP port this run listens on. Nothing takes it
    back at exit, so a reader checks what answers there before believing it."""
    port = _bound.get("http_port")
    if port is not None:
        device_registry.get_device_registry().set_self(port=port)


def published(registry: device_registry.DeviceRegistry | None = None) -> int | None:
    """The HTTP port a run of this install said it listens on, from `registry` or this
    install's own."""
    row = registry or device_registry.get_device_registry()
    port = row.self_get("port")
    return port if isinstance(port, int) and port > 0 else None


def forget() -> None:
    """Nothing has been bound. For a test that records a port."""
    _bound.clear()
