"""CloudRun 子进程失败必须停止整组，不能留下没有 worker 的健康 API。"""

import subprocess
from threading import Event

import pytest

from score_api.cloudrun import supervise


class Child:
    def __init__(self, code=None):
        self.code = code
        self.terminated = False

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def wait(self, timeout=None):
        return self.code


def test_failed_worker_stops_api_and_redis(monkeypatch):
    children = [Child(), Child(), Child(1)]
    pending = iter(children)
    monkeypatch.setattr(subprocess, "Popen", lambda _: next(pending))
    assert supervise([["redis"], ["api"], ["worker"]], Event()) == 1
    assert children[0].terminated and children[1].terminated


def test_partial_start_failure_cleans_up(monkeypatch):
    child = Child()

    def spawn(command):
        if command == ["missing"]:
            raise FileNotFoundError("missing")
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    with pytest.raises(FileNotFoundError):
        supervise([["redis"], ["missing"]], Event())
    assert child.terminated
