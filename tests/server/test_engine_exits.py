import asyncio
import logging

import pytest

from protean.domain import Domain
from protean.server.engine import Engine


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


@pytest.mark.no_test_domain
def test_engine_exits_if_no_subscriptions(caplog):
    # Configure the logger to capture INFO level messages
    logger = logging.getLogger("protean.server.engine")
    logger.setLevel(logging.INFO)

    domain = Domain(__file__, "dummy")
    engine = Engine(domain, test_mode=True)
    engine.run()

    assert any(
        record.levelname == "INFO"
        and "No subscriptions to start. Exiting..." in record.message
        for record in caplog.records
    )
