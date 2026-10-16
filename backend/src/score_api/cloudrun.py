"""CloudBase 单实例入口：监督 API、worker 与可丢弃的本机 Redis。"""

import os
import signal
import subprocess
import sys
import time
from threading import Event


def supervise(commands: list[list[str]], stop: Event) -> int:
    """任意子进程退出则停止整个实例，让平台重新启动完整服务。"""
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while not stop.wait(0.25):
            if any(child.poll() is not None for child in children):
                print("cloudrun_child_exited", file=sys.stderr, flush=True)
                return 1
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 20
        for child in children:
            try:
                child.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


def main() -> int:
    stop = Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    # 仅单实例可使用本机 Redis；平台 MinNum=MaxNum=1，不允许水平扩容。
    os.environ["SCORE_REDIS_URL"] = "redis://127.0.0.1:6379/0"
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    proxy_ips = os.environ.get("SCORE_TRUSTED_PROXY_IPS", "")
    if proxy_ips == "*":
        raise ValueError("Explicit trusted proxy IPs are required")
    api = [
        sys.executable,
        "-m",
        "uvicorn",
        "score_api.main:create_app",
        "--factory",
        "--host",
        "0.0.0.0",
        "--port",
        str(port),
        "--workers",
        "1",
        "--no-access-log",
    ]
    api += (
        ["--proxy-headers", "--forwarded-allow-ips", proxy_ips]
        if proxy_ips
        else ["--no-proxy-headers"]
    )
    return supervise(
        [
            [
                "redis-server",
                "--bind",
                "127.0.0.1",
                "--port",
                "6379",
                "--save",
                "",
                "--appendonly",
                "no",
                "--maxmemory",
                "64mb",
                "--maxmemory-policy",
                "noeviction",
            ],
            api,
            [sys.executable, "-m", "score_api.worker"],
        ],
        stop,
    )


if __name__ == "__main__":
    raise SystemExit(main())
