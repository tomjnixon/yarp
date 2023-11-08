from yarp import Value
from yarp.temporal import emit_at
from asyncio import Queue, wait_for, sleep
import pytest
from pytest import approx

tick = 0.2


def setup_emit_at(t, event_loop):
    e = emit_at(t)

    q = Queue()
    e.on_event(lambda ev: q.put_nowait((event_loop.time(), ev)))

    return e, q


@pytest.mark.asyncio
async def test_basic(event_loop):
    t = Value(event_loop.time() + tick)

    e, q = setup_emit_at(t, event_loop)

    tt, ev = await wait_for(q.get(), tick * 2)

    assert tt == approx(t.value, abs=tick / 2)
    assert ev is None


@pytest.mark.asyncio
async def test_value(event_loop):
    expected_t = event_loop.time() + tick
    t = Value((expected_t, 5))

    e, q = setup_emit_at(t, event_loop)

    tt, ev = await wait_for(q.get(), tick * 2)

    assert tt == approx(expected_t, abs=tick / 2)
    assert ev == 5

    await sleep(tick)
    assert q.empty()


@pytest.mark.asyncio
async def test_before_now(event_loop):
    t = Value(None)

    e, q = setup_emit_at(t, event_loop)

    now = event_loop.time()
    expected_t = now - tick
    for i in range(2):
        t.value = expected_t

        tt, ev = await wait_for(q.get(), tick)

        assert tt == approx(now, abs=tick / 2)
        assert ev is None

    await sleep(tick)
    assert q.empty()


@pytest.mark.asyncio
async def test_replace_unfired(event_loop):
    start = event_loop.time()
    t = Value((start + 2 * tick, 5))

    e, q = setup_emit_at(t, event_loop)

    t.value = (start + tick, 6)

    tt, ev = await wait_for(q.get(), tick * 2)

    assert tt == approx(start + tick, abs=tick / 2)
    assert ev == 6

    await sleep(tick * 2)
    assert q.empty()
