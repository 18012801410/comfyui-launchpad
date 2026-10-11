"""测试公共夹具：临时数据目录 + 已初始化令牌的应用实例。"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import SettingsStore
from app.core.paths import Layout, build_layout
from app.main import create_app


@pytest.fixture()
def layout(tmp_path: Path) -> Layout:
    lay = build_layout(data_dir=str(tmp_path / "data"))
    lay.ensure()
    return lay


@pytest.fixture()
def token(layout: Layout) -> str:
    return "test-token-abc123"


@pytest.fixture()
def client(layout: Layout, token: str) -> Iterator[TestClient]:
    store = SettingsStore(layout.state_dir / "config.json")
    store.initialize(token)
    app = create_app(settings_store=store, layout=layout)
    with TestClient(app) as c:
        yield c


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
