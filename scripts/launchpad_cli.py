#!/usr/bin/env python
"""LaunchPad 管理 CLI（由 install.sh / supervisor.sh 调用）。

命令:
  init [--reset] [--port N]   初始化配置，输出新令牌（仅此一次明文）
  port                        输出面板端口
  token-reset                 重新生成令牌并输出
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]  # /root/launchpad/current
sys.path.insert(0, str(REPO / "backend"))

from app.core.config import SettingsStore  # noqa: E402
from app.core.paths import build_layout  # noqa: E402
from app.core.security import generate_token  # noqa: E402

DEFAULT_PORT = 6006


def main() -> int:
    parser = argparse.ArgumentParser(prog="launchpad")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化配置并输出令牌")
    p_init.add_argument("--reset", action="store_true", help="重置令牌与配置")
    p_init.add_argument("--port", type=int, default=DEFAULT_PORT)

    sub.add_parser("port", help="输出面板端口")

    sub.add_parser("token-reset", help="重新生成令牌")

    args = parser.parse_args()

    layout = build_layout()
    layout.ensure()
    store = SettingsStore(layout.state_dir / "config.json")

    panel_port = int(os.environ.get("LAUNCHPAD_PORT", DEFAULT_PORT))

    if args.cmd == "init":
        reset = args.reset or not store.exists()
        if reset:
            token = generate_token()
            settings = store.initialize(token)
            if args.port:
                panel_port = args.port
            settings = settings.model_copy(update={"panel_port": panel_port})
            store.save(settings)
            print(f"面板端口 {panel_port} 初始化完成")
            print(token)
        else:
            settings = store.load()
            assert settings is not None
            if args.port and args.port != settings.panel_port:
                store.save(settings.model_copy(update={"panel_port": args.port}))
                panel_port = args.port
            print(f"面板端口 {panel_port}（配置保留）")
            print("TOKEN-UNCHANGED")
        return 0

    if args.cmd == "port":
        settings = store.load()
        print(settings.panel_port if settings else panel_port)
        return 0

    if args.cmd == "token-reset":
        settings = store.load()
        if settings is None:
            print("面板尚未初始化，请先运行 init", file=sys.stderr)
            return 1
        new_token = generate_token()
        store.rotate_token(settings, new_token)
        print(new_token)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
