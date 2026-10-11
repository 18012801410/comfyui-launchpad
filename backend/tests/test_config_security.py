"""配置持久化测试：原子写、备份回退、损坏处理、令牌哈希校验。"""

import json
import os
from pathlib import Path

import pytest

from app.core.config import (
    ConfigCorruptedError,
    SettingsStore,
    read_json_with_backup,
    write_json_atomic,
)
from app.core.security import (
    TokenMaskFilter,
    generate_token,
    hash_token,
    new_salt,
    verify_token,
)


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "x.json"
    write_json_atomic(path, {"a": 1})
    assert read_json_with_backup(path) == {"a": 1}


def test_atomic_write_failure_keeps_old_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "x.json"
    write_json_atomic(path, {"v": 1})

    def boom(src: object, dst: object) -> None:
        raise RuntimeError("模拟 rename 前崩溃")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(RuntimeError):
        write_json_atomic(path, {"v": 2})
    # 正式路径保持旧内容，无 .tmp 残留
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1}
    assert not list(tmp_path.glob("*.tmp"))


def test_corrupt_main_falls_back_to_bak(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    write_json_atomic(path, {"v": 1})
    write_json_atomic(path, {"v": 2})
    # .bak 保存的是上一次成功写入（v1）：主文件损坏后回退到它，只损失最后一次写入
    path.write_text("{broken", encoding="utf-8")
    assert read_json_with_backup(path) == {"v": 1}


def test_both_corrupted_raises(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{a", encoding="utf-8")
    path.with_name("x.json.bak").write_text("{b", encoding="utf-8")
    with pytest.raises(ConfigCorruptedError):
        read_json_with_backup(path)


def test_settings_initialize_verify_rotate(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.json")
    token = generate_token()
    store.initialize(token)
    assert store.exists()
    assert store.verify(token)
    assert not store.verify("wrong-token")

    new_token = generate_token()
    settings = store.load()
    assert settings is not None
    store.rotate_token(settings, new_token)
    assert store.verify(new_token)
    assert not store.verify(token)  # 旧令牌立即失效


def test_missing_settings_returns_none(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "nope.json")
    assert store.load() is None
    assert not store.verify("anything")


def test_token_hashing() -> None:
    token = generate_token()
    salt = new_salt()
    h = hash_token(token, salt)
    assert h != token
    assert len(token) >= 32
    assert verify_token(token, salt, h)
    assert not verify_token(token + "x", salt, h)
    assert hash_token(token, salt) == hash_token(token, salt)
    assert hash_token(token, new_salt()) != h


def test_token_mask_filter() -> None:
    import logging

    token = "SECRETVALUE123"
    filt = TokenMaskFilter(token)
    record = logging.LogRecord(
        "t", logging.INFO, "p", 1, "token=%s and SECRETVALUE123", (token,), None
    )
    assert filt.filter(record) is True
    text = record.getMessage()
    assert "SECRETVALUE123" not in text
    assert "***" in text
