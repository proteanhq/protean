"""Run the example on ``docs/reference/adapters/eventstore/index.md``."""

from uuid import uuid4

import pytest

from protean import Domain
from protean.adapters.event_store.message_db import MessageDBStore
from tests.docs.support import DOCS_SRC, load_example
from tests.shared import MESSAGE_DB_URI

MESSAGE_DB_CONFIG = DOCS_SRC / "adapters/eventstore/index/message_db.toml"

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example():
    return load_example("adapters/eventstore/index/001.py")


def test_stream_name_is_category_and_identifier(example):
    assert example.stream == f"banking::account-{example.account.id}"


def test_reads_from_the_start_and_from_a_position(example):
    # Opened, Deposited 100.0, Deposited 50.0, then the handler's 25.0
    # deposit is appended later, in the causation section
    assert len(example.messages) == 3
    assert len(example.later) == 2
    assert [m.data.get("amount") for m in example.later] == [100.0, 50.0]
    assert example.last.data["amount"] == 50.0


def test_aggregate_loads_at_a_version_and_a_time(example):
    # Version 0 is the state right after the first event
    assert example.opened.balance == 0.0
    assert example.current.balance == 150.0


def test_snapshots_are_created(example):
    assert example.created is True
    assert example.count == 1

    # One snapshot from each call, both holding the state after two deposits
    snapshot_stream = f"banking::account:snapshot-{example.account.id}"
    with example.domain.domain_context():
        # Snapshots are raw records, not domain messages, so read them raw
        snapshots = example.domain.event_store.store._read(snapshot_stream)

    assert len(snapshots) == 2
    assert [m["data"]["balance"] for m in snapshots] == [150.0, 150.0]


def test_causation_links_the_command_to_its_event(example):
    assert [m.metadata.headers.type for m in example.chain] == [
        "Banking.Deposit.v1",
        "Banking.Deposited.v1",
    ]
    assert [m.metadata.headers.type for m in example.effects] == [
        "Banking.Deposited.v1"
    ]
    assert example.tree.message_type == "Banking.Deposit.v1"
    assert [child.message_type for child in example.tree.children] == [
        "Banking.Deposited.v1"
    ]


@pytest.mark.message_db
def test_message_db_configuration_connects(tmp_path, monkeypatch):
    (tmp_path / "domain.toml").write_text(MESSAGE_DB_CONFIG.read_text())
    monkeypatch.setenv("MESSAGE_DB_URL", MESSAGE_DB_URI)
    domain = Domain(root_path=str(tmp_path), name="Banking")
    domain.init(traverse=False)

    stream = f"doc_check-{uuid4()}"
    with domain.domain_context():
        store = domain.event_store.store
        store._write(stream, "Checked", {"n": 1})

        assert isinstance(store, MessageDBStore)
        assert [m["data"] for m in store._read(stream)] == [{"n": 1}]
