"""launchpad_cli.py 回归测试（安装流程依赖它）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CLI = Path(__file__).parents[2] / "scripts" / "launchpad_cli.py"


def run_cli(args: list[str], data_dir: Path) -> subprocess.CompletedProcess[str]:
    import os

    env = os.environ.copy()
    env["LAUNCHPAD_DATA_DIR"] = str(data_dir)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_cli_init_port_reset(tmp_path: Path) -> None:
    # 首次 init：输出端口信息 + 令牌
    r1 = run_cli(["init", "--port", "6006"], tmp_path)
    assert r1.returncode == 0
    lines = r1.stdout.strip().splitlines()
    assert "6006" in lines[0]
    token = lines[-1]
    assert len(token) >= 32

    # 幂等 init：令牌不变
    r2 = run_cli(["init", "--port", "6006"], tmp_path)
    assert "TOKEN-UNCHANGED" in r2.stdout

    # port 子命令
    r3 = run_cli(["port"], tmp_path)
    assert r3.stdout.strip() == "6006"

    # token-reset：新令牌 ≥32 字符且不同
    r4 = run_cli(["token-reset"], tmp_path)
    new_token = r4.stdout.strip()
    assert len(new_token) >= 32
    assert new_token != token
