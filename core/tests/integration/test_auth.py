"""Integration tests for /api/v1/auth (Phase 2 acceptance criterion)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


class TestLogin:
    async def test_valid_credentials_returns_token_pair(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"] != body["refresh_token"]
        assert "access_expires_at" in body
        assert "refresh_expires_at" in body

    async def test_wrong_password_returns_401(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_EMAIL, "password": "wrong-password"},
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "INVALID_CREDENTIALS"

    async def test_unknown_user_returns_401(self, app_and_client: tuple[Any, AsyncClient]) -> None:
        _, client = app_and_client
        resp = await client.post(
            "/api/v1/auth/login",
            data={"username": "unknown@test.local", "password": ADMIN_PASSWORD},
        )
        assert resp.status_code == 401


class TestRefresh:
    async def test_refresh_returns_new_token_pair(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        refresh_token = login_resp.json()["refresh_token"]

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["refresh_token"]

    async def test_access_token_cannot_refresh(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        login_resp = await client.post(
            "/api/v1/auth/login",
            data={"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        access_token = login_resp.json()["access_token"]

        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_REQUIRED"

    async def test_garbage_token_returns_401(self, app_and_client: tuple[Any, AsyncClient]) -> None:
        _, client = app_and_client
        resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-jwt"})
        assert resp.status_code == 401


class TestProtectedRoute:
    async def test_unauth_request_returns_401(
        self, app_and_client: tuple[Any, AsyncClient]
    ) -> None:
        _, client = app_and_client
        resp = await client.get("/api/v1/clients")
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_REQUIRED"

    async def test_invalid_token_returns_401(self, app_and_client: tuple[Any, AsyncClient]) -> None:
        _, client = app_and_client
        resp = await client.get(
            "/api/v1/clients", headers={"Authorization": "Bearer not-a-real-jwt"}
        )
        assert resp.status_code == 401
        assert resp.json()["code"] == "AUTH_REQUIRED"
