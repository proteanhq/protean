"""The engine checks a real SQLite file for its outbox table at startup."""

import pytest

from protean import Engine
from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import String


class Record(BaseAggregate):
    name = String()


@pytest.fixture
def domain(tmp_path):
    domain = Domain(name="Test")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{tmp_path / 'test.db'}",
    }
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.register(Record)
    domain.init(traverse=False)

    with domain.domain_context():
        yield domain
        domain.drop_database()
        domain.close()


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestEngineOutboxTableOnSqlite:
    def test_engine_stops_when_the_outbox_table_is_missing(self, domain):
        with pytest.raises(ConfigurationError) as exc:
            Engine(domain, test_mode=True)

        assert str(exc.value) == (
            "Outbox table not found for provider 'default'. "
            "Run 'protean db setup' or 'protean db setup-outbox' to create it."
        )

    def test_engine_starts_once_the_outbox_table_exists(self, domain):
        domain.setup_outbox()

        engine = Engine(domain, test_mode=True)

        assert "outbox-processor-default-to-default" in engine._outbox_processors


@pytest.mark.sqlite
@pytest.mark.no_test_domain
def test_engine_skips_the_check_when_the_outbox_is_off(tmp_path):
    domain = Domain(name="Test")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": f"sqlite:///{tmp_path / 'test.db'}",
    }
    domain.config["server"]["default_subscription_type"] = "event_store"
    domain.register(Record)
    domain.init(traverse=False)

    with domain.domain_context():
        try:
            engine = Engine(domain, test_mode=True)

            assert engine._outbox_processors == {}
        finally:
            domain.close()
