"""测试用 fake ComfyUI 子进程。

用法：python fake_comfy.py --hold 3 --port 0 --lines 2 --exit-code 0
行为：打印 N 行日志 → 绑定端口（>0 时）打印 ready → 保持 hold 秒 → 以 exit-code 退出。
"""

from __future__ import annotations

import argparse
import socket
import sys
import time


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--hold", type=float, default=3.0)
    p.add_argument("--port", type=int, default=0, help="0=不监听; -1=自动挑选空闲端口")
    p.add_argument("--lines", type=int, default=2)
    p.add_argument("--exit-code", type=int, default=0)
    p.add_argument("--delay", type=float, default=0.0, help="启动前延迟")
    args = p.parse_args()

    if args.delay:
        time.sleep(args.delay)
    for i in range(max(0, args.lines)):
        print(f"[fake-comfy] log line {i + 1}", flush=True)

    port = args.port
    if port == -1:
        port = free_port()
    if port > 0:
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(1)
        print(f"[fake-comfy] ready on {port}", flush=True)

    deadline = time.monotonic() + args.hold
    while time.monotonic() < deadline:
        time.sleep(0.05)
    print(f"[fake-comfy] exiting with {args.exit_code}", flush=True)
    return args.exit_code


if __name__ == "__main__":
    sys.exit(main())
