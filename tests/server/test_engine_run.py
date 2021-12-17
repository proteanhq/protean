import pytest

from protean import Engine


@pytest.mark.skip(reason="Yet to implement")
def test_running_subscriptions_on_engine_start():
    engine = Engine.from_domain_file(
        domain="baz", domain_file="tests/server/dummy_domain.py", test_mode=True
    )
    engine.run()
