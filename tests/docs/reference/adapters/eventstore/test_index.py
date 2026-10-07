"""Run the example on ``docs/reference/adapters/eventstore/index.md``."""

import pytest

from tests.docs.support import load_example

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
