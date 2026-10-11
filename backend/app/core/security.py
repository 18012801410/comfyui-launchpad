"""令牌安全：生成、盐哈希存储、常量时间校验、日志脱敏。

安全不变量（docs/TECH_SPEC.md「安全」节）：令牌只存盐哈希；校验用常量时间比较；
令牌明文不出现在任何日志与错误信息中。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def generate_token() -> str:
    """生成 32+ 字符 URL 安全随机令牌。"""
    return secrets.token_urlsafe(32)


def new_salt() -> str:
    return secrets.token_hex(16)


def hash_token(token: str, salt: str) -> str:
    return hashlib.scrypt(
        token.encode("utf-8"), salt=salt.encode("utf-8"), n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    ).hex()


def verify_token(token: str, salt: str, expected_hash: str) -> bool:
    actual = hash_token(token, salt)
    return hmac.compare_digest(actual, expected_hash)


def mask_text(text: str, token: str | None, replacement: str = "***") -> str:
    if not token:
        return text
    return text.replace(token, replacement)


class TokenMaskFilter(logging.Filter):
    """日志过滤器：把记录中的令牌明文替换为占位符。"""

    def __init__(self, token: str | None) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if self._token:
            if isinstance(record.msg, str):
                record.msg = mask_text(record.msg, self._token)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {
                        k: mask_text(v, self._token) if isinstance(v, str) else v
                        for k, v in record.args.items()
                    }
                else:
                    record.args = tuple(
                        mask_text(a, self._token) if isinstance(a, str) else a
                        for a in record.args
                    )
        return True
