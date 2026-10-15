"""每 API 进程的有界短时快照缓存；调用方必须先独立校验授权及版本。"""

import time
from collections import OrderedDict
from concurrent.futures import Future, TimeoutError
from threading import Lock

from score_api.core.errors import APIError


class SnapshotCache:
    def __init__(self, *, ttl=1.0, capacity=128, clock=time.monotonic):
        self.ttl, self.capacity, self.clock = ttl, capacity, clock
        self.values = OrderedDict()
        self.pending = {}
        self.lock = Lock()

    def get(self, key, loader):
        with self.lock:
            cached = self.values.get(key)
            if cached and cached[0] > self.clock():
                self.values.move_to_end(key)
                return cached[1].model_copy(deep=True)
            self.values.pop(key, None)
            future = self.pending.get(key)
            leader = future is None
            if leader:
                if len(self.pending) >= self.capacity:
                    raise APIError(503, "SERVICE_UNAVAILABLE", "快照请求繁忙", retry_after=3)
                future = self.pending[key] = Future()
        if not leader:
            try:
                return future.result(timeout=10).model_copy(deep=True)
            except TimeoutError:
                raise APIError(503, "SERVICE_UNAVAILABLE", "快照请求繁忙", retry_after=3) from None
        try:
            value = loader()
            with self.lock:
                self.values[key] = (self.clock() + self.ttl, value)
                while len(self.values) > self.capacity:
                    self.values.popitem(last=False)
            future.set_result(value)
            return value.model_copy(deep=True)
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.pending.pop(key, None)
