import asyncio

import pytest

from protean import Engine


@pytest.fixture(autouse=True)
def auto_set_and_close_loop():
    # Create and set a new loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    yield

    # Close the loop after the test
    if not loop.is_closed():
        loop.close()
    asyncio.set_event_loop(None)  # Explicitly unset the loop


def test_that_engine_can_be_initialized_from_a_domain_object(test_domain):
    engine = Engine(test_domain)
    assert engine.domain == test_domain


def test_loop_initialization_within_engine(test_domain):
    engine = Engine(test_domain)
    assert engine.loop is not None
    assert isinstance(engine.loop, asyncio.SelectorEventLoop)
    assert engine.loop.is_running() is False
    assert engine.loop.is_closed() is False
