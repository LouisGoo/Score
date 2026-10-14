import asyncio

from score_api.realtime.broker import Broker


def test_broker_isolates_events_and_disconnects_slow_consumers():
    async def run():
        broker = Broker("redis://localhost:6379/15")
        first, second = broker.attach("a"), broker.attach("b")
        for version in range(65):
            broker.dispatch({"event_id": "a", "version": version})
        assert first.qsize() == 1 and first.get_nowait() is None
        assert first not in broker.queues and second.empty()
        broker.ready = True
        broker.disconnect()
        assert not broker.ready and second.get_nowait() is None
        await broker.redis.aclose()

    asyncio.run(run())
