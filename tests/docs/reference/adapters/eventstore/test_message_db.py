"""Load the configuration on ``docs/reference/adapters/eventstore/message-db.md``."""

from uuid import uuid4

import pytest

from protean.adapters.event_store.message_db import MessageDBStore
from tests.docs.support import domain_from_config
from tests.shared import MESSAGE_DB_URI

CONFIG = "adapters/eventstore/message-db/configuration.toml"

pytestmark = pytest.mark.no_test_domain


@pytest.mark.message_db
def test_configuration_shown_connects(tmp_path, monkeypatch):
    monkeypatch.setenv("MESSAGE_DB_URL", MESSAGE_DB_URI)
    domain = domain_from_config(CONFIG, tmp_path)
    domain.init(traverse=False)

    stream = f"doc_check-{uuid4()}"
    with domain.domain_context():
        store = domain.event_store.store
        store._write(stream, "Checked", {"n": 1})

        assert type(store) is MessageDBStore
        assert [m["data"] for m in store._read(stream)] == [{"n": 1}]


def test_configuration_shown_defaults_to_the_documented_uri(tmp_path, monkeypatch):
    monkeypatch.delenv("MESSAGE_DB_URL", raising=False)
    domain = domain_from_config(CONFIG, tmp_path)

    assert (
        domain.config["event_store"]["database_uri"]
        == "postgresql://postgres:postgres@localhost:5433/message_store"
    )
