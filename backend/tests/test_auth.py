"""TASK-003 验收：鉴权全局性、auth 三端点、错误包络。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import SettingsStore
from app.core.paths import build_layout
from app.main import create_app
from tests.conftest import auth_header

PROTECTED_PREFIX = "/panel/api/versions"  # TASK-008 才有真实路由，这里用一个确定存在的受保护路由


def test_health_loopback_allowed(client: TestClient) -> None:
    resp = client.get("/panel/api/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_protected_routes_require_token(client: TestClient) -> None:
    # 未带令牌 → 401 auth_required（对任何受保护路由）
    resp = client.get("/panel/api/panel/settings")
    assert resp.status_code == 401
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "auth_required"


def test_verify_ok_and_wrong(client: TestClient, token: str) -> None:
    ok_resp = client.post("/panel/api/auth/verify", json={"token": token})
    assert ok_resp.status_code == 200
    assert ok_resp.json()["data"]["panel_version"]

    bad = client.post("/panel/api/auth/verify", json={"token": "nope"})
    assert bad.status_code == 401
    assert bad.json()["error"]["code"] == "invalid_token"


def test_rotate_invalidates_old_token(client: TestClient, token: str) -> None:
    resp = client.post("/panel/api/auth/rotate", headers=auth_header(token))
    assert resp.status_code == 200
    new_token = resp.json()["data"]["token"]
    assert new_token and new_token != token

    # 旧令牌立即失效
    old = client.post("/panel/api/auth/verify", json={"token": token})
    assert old.status_code == 401
    # 新令牌可用
    new = client.post("/panel/api/auth/verify", json={"token": new_token})
    assert new.status_code == 200


def test_rotate_requires_token(client: TestClient) -> None:
    resp = client.post("/panel/api/auth/rotate")
    assert resp.status_code == 401


def test_app_error_handler_envelope(tmp_path: Path) -> None:
    """业务异常 → 统一错误包络；未知异常 → internal 且不泄露堆栈。"""
    from fastapi import APIRouter

    from app.api.errors import AppError
    from app.core.paths import build_layout

    lay = build_layout(data_dir=str(tmp_path / "d"))
    lay.ensure()
    store = SettingsStore(lay.state_dir / "config.json")
    store.initialize("t")

    router = APIRouter()

    @router.get("/panel/api/_boom_app")
    def boom_app() -> None:
        raise AppError("port_conflict", "端口被占用", status=409)

    @router.get("/panel/api/_boom_int")
    def boom_int() -> None:
        raise RuntimeError("secret stack detail")

    # extra_routers 在静态挂载之前注册，验证异常包络不受 SPA mount 影响
    app = create_app(settings_store=store, layout=lay, extra_routers=[router])
    c = TestClient(app, raise_server_exceptions=False)

    r1 = c.get("/panel/api/_boom_app")
    assert r1.status_code == 409
    assert r1.json() == {
        "ok": False,
        "error": {"code": "port_conflict", "message": "端口被占用"},
    }

    r2 = c.get("/panel/api/_boom_int")
    assert r2.status_code == 500
    body = r2.json()
    assert body["error"]["code"] == "internal"
    assert "secret" not in body["error"]["message"]


def test_uninitialized_panel_requires_setup(tmp_path: Path) -> None:
    lay = build_layout(data_dir=str(tmp_path / "d2"))
    lay.ensure()
    app = create_app(settings_store=SettingsStore(lay.state_dir / "config.json"), layout=lay)
    c = TestClient(app)
    resp = c.post("/panel/api/auth/verify", json={"token": "x"})
    assert resp.status_code == 401


@pytest.mark.parametrize("malformed", ["", "Bearer", "Basic abc", "Bearer "])
def test_malformed_auth_header_401(client: TestClient, malformed: str) -> None:
    resp = client.get(
        "/panel/api/panel/settings",
        headers={"Authorization": malformed} if malformed else {},
    )
    assert resp.status_code == 401
