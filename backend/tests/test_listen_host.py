"""listen_host（对外暴露开关，方案 A）测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.domain.launch_config import LaunchConfig
from tests.conftest import auth_header


def test_default_listen_host_is_local() -> None:
    cfg = LaunchConfig()
    args = cfg.build_cli_args(panel_port=6006)
    assert args == ["--listen", "127.0.0.1", "--port", "8188"]


def test_exposed_host_builds_zero_listen() -> None:
    cfg = LaunchConfig(listen_host="0.0.0.0", listen_port=6008)
    args = cfg.build_cli_args(panel_port=6006)
    assert args == ["--listen", "0.0.0.0", "--port", "6008"]


def test_invalid_host_rejected() -> None:
    with pytest.raises(ValidationError):
        LaunchConfig(listen_host="192.168.1.1")  # type: ignore[arg-type]


def test_api_roundtrip_listen_host(client: TestClient, token: str) -> None:
    r = client.put(
        "/api/comfy/launch-config",
        json={"listen_host": "0.0.0.0", "listen_port": 6008},
        headers=auth_header(token),
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["listen_host"] == "0.0.0.0"
    assert data["listen_port"] == 6008

    r2 = client.get("/api/comfy/launch-config", headers=auth_header(token))
    assert r2.json()["data"]["listen_host"] == "0.0.0.0"

    # 非法 host → 422
    r3 = client.put(
        "/api/comfy/launch-config",
        json={"listen_host": "example.com"},
        headers=auth_header(token),
    )
    assert r3.status_code == 422
