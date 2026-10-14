"""An app for the routes core writes for an extension, without the API's sign-in.

`httpapi.create_api_app()` is the whole thing; a test that wants one extension's routes and
nothing else mounts them here, with every scope granted.
"""

from __future__ import annotations

import unittest
from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from common import extensions
from common.extensions import host
from httpapi import errors, extensions_served


class _Holding:
    def __init__(self, allowed: Callable[[str], bool]) -> None:
        self._allowed = allowed

    def can(self, scope: str) -> bool:
        return self._allowed(scope)


def client_for(test: unittest.TestCase, registry: Any, record: Any,
               allowed: Callable[[str], bool] = lambda _scope: True,
               **options: Any) -> TestClient:
    """A client over the routes core serves for `record`, at `/ext/<name>`. The routes ask
    the process's registry, so `registry` is made that one until the test is over. Every
    scope is held unless `allowed` says which are."""
    async def _everyone(request: Request) -> None:
        request.state.identity = _Holding(allowed)

    extensions.set_registry(registry)
    test.addCleanup(extensions.set_registry, host.Registry())
    app = FastAPI(dependencies=[Depends(_everyone)])
    errors.install_error_handlers(app)
    app.include_router(extensions_served.router(record.name, Depends(lambda: None)),
                       prefix=f"/ext/{record.name}")
    for router, _scope in record.routers:
        app.include_router(router, prefix=f"/ext/{record.name}")
    return TestClient(app, **options)
