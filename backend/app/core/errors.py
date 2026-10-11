"""带稳定错误码的业务异常。

放在 core 层：领域模块需要抛出带码异常，而领域层不得依赖 api 层。
API 层负责把它序列化为统一错误包络。
"""

from __future__ import annotations


class AppError(Exception):
    """带稳定错误码的业务异常；API 层统一转为错误包络。"""

    status = 400

    def __init__(self, code: str, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        if status is not None:
            self.status = status


class InvalidTransition(AppError):
    """进程状态机非法迁移（领域守卫）。"""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            "internal", f"非法状态迁移: {current} -> {target}", status=500
        )
