"""An app for the routes core writes for an extension, without the API's sign-in.

`httpapi.create_api_app()` is the whole thing; a test that wants one extension's routes and
nothing else mounts them here, with every scope granted.
"""

from __future__ import annotations

import unittest
from typing import Any

from fastapi import Depends, FastAPI, Request
from starlette.testclient import TestClient

from common import extensions
from common.extensions import host
from httpapi import errors, extensions_served


class _Everything:
    def can(self, _scope: str) -> bool:
        return True


async def _everyone(request: Request) -> None:
    request.state.identity = _Everything()


def client_for(test: unittest.TestCase, registry: Any, record: Any,
               **options: Any) -> TestClient:
    """A client over the routes core serves for `record`, at `/ext/<name>`. The routes ask
    the process's registry, so `registry` is made that one until the test is over."""
    extensions.set_registry(registry)
    test.addCleanup(extensions.set_registry, host.Registry())
    app = FastAPI(dependencies=[Depends(_everyone)])
    errors.install_error_handlers(app)
    app.include_router(extensions_served.router(record.name, Depends(lambda: None)),
                       prefix=f"/ext/{record.name}")
    for router, _scope in record.routers:
        app.include_router(router, prefix=f"/ext/{record.name}")
    return TestClient(app, **options)
