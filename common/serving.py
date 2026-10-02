"""The ports this process answers on.

A port setting is read once, by the server that binds it, and changing it afterwards moves
nothing until the next start. Anything addressing this running install asks here; the
setting would send it to a port nothing is listening on.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal

from common.config_access import NetworkConfig

Port = Literal["http_port", "ws_port", "theme_assets_port"]
_bound: dict[str, int] = {}


def bound(field: Port, port: int) -> None:
    """Record the port a server was started on, under its `NetworkConfig` field."""
    _bound[field] = int(port)


def network(config: Any) -> NetworkConfig:
    """The network settings as this process serves them: each port a server here was
    started on, and the setting for one nothing here has started."""
    configured = NetworkConfig.from_config(config)
    return dataclasses.replace(
        configured,
        http_port=_bound.get("http_port", configured.http_port),
        ws_port=_bound.get("ws_port", configured.ws_port),
        theme_assets_port=_bound.get("theme_assets_port", configured.theme_assets_port))


def forget() -> None:
    """Nothing has been bound. For a test that records a port."""
    _bound.clear()
