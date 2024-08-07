import logging

import pytest

from protean.domain import Domain
from protean.server.engine import Engine


@pytest.mark.no_test_domain
def test_engine_exits_if_no_subscriptions(caplog):
    # Configure the logger to capture INFO level messages
    logger = logging.getLogger("protean.server.engine")
    logger.setLevel(logging.INFO)

    domain = Domain("dummy", load_toml=False)
    engine = Engine(domain, test_mode=True)
    engine.run()

    assert any(
        record.levelname == "INFO"
        and "No subscriptions to start. Exiting..." in record.message
        for record in caplog.records
    )
