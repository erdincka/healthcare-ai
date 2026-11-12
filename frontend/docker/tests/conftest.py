"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

import ai_client


@pytest.fixture
def fake_server(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Route ai_client's HTTP calls to a handler; returns the list of captured requests."""

    def install(status: int, body: dict[str, Any]) -> list[httpx.Request]:
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(status, json=body)

        real_client = httpx.AsyncClient

        def client(**kwargs: Any) -> httpx.AsyncClient:
            kwargs.pop("verify", None)
            return real_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(ai_client.httpx, "AsyncClient", client)
        return captured

    return install
