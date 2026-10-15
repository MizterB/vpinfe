"""Fetching a theme catalog and checking it is one before trusting it."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import urlsplit

import requests

from common.failures import why
from common.http_client import get_bytes, get_json
from common.i18n import t


class ThemeRegistryError(Exception):
    pass


class ThemeRegistryClient:
    """Fetches one theme catalog and validates its shape before returning it."""

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout

    def fetch_json(self, url: str) -> dict:
        try:
            payload = get_json(url, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ThemeRegistryError(why(exc, url)) from exc
        except ValueError as exc:
            raise ThemeRegistryError(why(exc)) from exc

        if not isinstance(payload, dict):
            raise ThemeRegistryError(t("said.why.unreadable_at",
                                       host=urlsplit(url).hostname or url))
        return payload

    def download_zip(self, url: str) -> BytesIO:
        try:
            return BytesIO(get_bytes(url))
        except requests.RequestException as exc:
            raise ThemeRegistryError(why(exc, url)) from exc
