import asyncio

from protean import Engine


def test_that_engine_can_be_initialized_from_a_domain_object(test_domain):
    engine = Engine(test_domain)
    assert engine.domain == test_domain


def test_loop_initialization_within_engine(test_domain):
    engine = Engine(test_domain)
    assert engine.loop is not None
    assert isinstance(engine.loop, asyncio.SelectorEventLoop)
    assert engine.loop.is_running() is False
    assert engine.loop.is_closed() is False
