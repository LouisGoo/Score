"""每个 API 进程一个 Redis 订阅；有界连接队列，断流时关闭连接要求重新同步。"""

import asyncio
import json
from contextlib import suppress

from redis.asyncio import Redis
from redis.exceptions import RedisError

CHANNEL = "score:events:v1"


class Broker:
    def __init__(self, url):
        self.redis = Redis.from_url(url, socket_connect_timeout=2, socket_timeout=3)
        self.queues = {}
        self.ready = False

    def attach(self, event_id):
        queue = asyncio.Queue(maxsize=64)
        self.queues[queue] = event_id
        return queue

    def detach(self, queue):
        self.queues.pop(queue, None)

    def disconnect(self):
        self.ready = False
        for queue in list(self.queues):
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(None)

    def dispatch(self, message):
        for queue, event_id in list(self.queues.items()):
            if message.get("event_id") != event_id:
                continue
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self.detach(queue)
            else:
                queue.put_nowait(message)

    async def run(self):
        delay = 0.5
        try:
            while True:
                try:
                    async with self.redis.pubsub() as pubsub:
                        await pubsub.subscribe(CHANNEL)
                        # 等订阅确认才允许签发票据，避免连接建立时丢掉首条通知。
                        while True:
                            msg = await pubsub.get_message(timeout=1)
                            if msg is None:
                                continue
                            if msg["type"] == "subscribe":
                                self.ready = True
                                delay = 0.5
                            elif msg["type"] == "message":
                                try:
                                    self.dispatch(json.loads(msg["data"]))
                                except (ValueError, TypeError, AttributeError):
                                    self.disconnect()
                                    break
                except (RedisError, OSError):
                    self.disconnect()
                await asyncio.sleep(delay)
                delay = min(15, delay * 2)
        finally:
            self.disconnect()
            await self.redis.aclose()


async def stop(task):
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
