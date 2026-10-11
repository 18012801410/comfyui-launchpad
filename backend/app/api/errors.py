"""业务异常与稳定错误码（docs/API_SPEC.md「稳定错误码」）。"""

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


def auth_required(message: str = "需要访问令牌") -> AppError:
    return AppError("auth_required", message, status=401)


def invalid_token(message: str = "令牌不正确") -> AppError:
    return AppError("invalid_token", message, status=401)


def conflict_process_running(message: str = "ComfyUI 正在运行，禁止该操作") -> AppError:
    return AppError("conflict_process_running", message, status=409)


def conflict_install_in_progress(message: str = "已有安装任务进行中") -> AppError:
    return AppError("conflict_install_in_progress", message, status=409)


def version_not_installed(message: str = "该版本未安装") -> AppError:
    return AppError("version_not_installed", message, status=404)


def version_not_ready(message: str = "该版本未就绪") -> AppError:
    return AppError("version_not_ready", message, status=409)


def version_in_use(message: str = "该版本正在使用，禁止删除") -> AppError:
    return AppError("version_in_use", message, status=409)


def path_forbidden(message: str = "路径越出白名单") -> AppError:
    return AppError("path_forbidden", message, status=403)


def invalid_launch_args(message: str = "启动参数非法") -> AppError:
    return AppError("invalid_launch_args", message, status=400)


def invalid_workflow(message: str = "不是有效的 ComfyUI 工作流 JSON") -> AppError:
    return AppError("invalid_workflow", message, status=400)


def download_failed(message: str = "下载失败") -> AppError:
    return AppError("download_failed", message, status=502)


def checksum_mismatch(message: str = "校验和不匹配") -> AppError:
    return AppError("checksum_mismatch", message, status=502)


def disk_insufficient(message: str = "磁盘空间不足") -> AppError:
    return AppError("disk_insufficient", message, status=507)


def port_conflict(message: str = "端口被占用") -> AppError:
    return AppError("port_conflict", message, status=409)


def plugin_update_failed(message: str = "插件更新失败") -> AppError:
    return AppError("plugin_update_failed", message, status=500)


def index_unavailable(message: str = "版本索引不可达且无缓存") -> AppError:
    return AppError("index_unavailable", message, status=502)
