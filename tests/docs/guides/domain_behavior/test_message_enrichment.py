"""The examples on the message enrichment guide behave as the page says."""

from types import SimpleNamespace

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

REQUEST = {
    "current_user": SimpleNamespace(id="u-123"),
    "tenant_id": "acme-corp",
    "client_ip": "10.0.0.1",
    "request_id": "req-1",
}
EVENT_EXTENSIONS = {
    "user_id": "u-123",
    "tenant_id": "acme-corp",
    "ip_address": "10.0.0.1",
}


@pytest.fixture
def enrichers():
    example = load_example("guides/domain-behavior/message-enrichment/001.py")
    example.domain.init(traverse=False)
    return example


def test_event_enrichers_add_the_request_context(enrichers, capsys):
    with enrichers.domain.domain_context(**REQUEST):
        enrichers.show_extensions(enrichers.User(email="jane@example.com"))

    assert capsys.readouterr().out.strip() == str(EVENT_EXTENSIONS)


def test_event_enrichers_fall_back_when_there_is_no_request(enrichers):
    with enrichers.domain.domain_context():
        user = enrichers.User(email="jane@example.com")
        user.register()

    assert user._events[0]._metadata.extensions == {
        "user_id": "system",
        "tenant_id": None,
        "ip_address": None,
    }


def test_extensions_survive_serialization(enrichers, capsys):
    with enrichers.domain.domain_context(**REQUEST):
        user = enrichers.User(email="jane@example.com")
        user.register()
        enrichers.round_trip(user._events[0])

    assert capsys.readouterr().out.splitlines() == [str(EVENT_EXTENSIONS)] * 2


def test_command_enrichers_add_the_request_context(enrichers):
    with enrichers.domain.domain_context(**REQUEST):
        enrichers.domain.process(
            enrichers.RegisterUser(user_id="x1", email="jane@example.com"),
            asynchronous=False,
        )
        stored = enrichers.domain.event_store.store.read_last_message(
            f"{enrichers.User.meta_.stream_category}:command-x1"
        )

    assert stored.metadata.extensions == {
        "request_id": "req-1",
        "ip_address": "10.0.0.1",
    }


def test_later_enrichers_win_on_a_shared_key():
    example = load_example("guides/domain-behavior/message-enrichment/002.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        account = example.Account()
        account.open()

    assert account._events[0]._metadata.extensions == {
        "source": "tenant-enricher",
        "user_id": "u-123",
        "tenant_id": "t-456",
    }


def test_the_aggregate_enricher_stamps_the_audit_fields_on_save():
    example = load_example("guides/domain-behavior/message-enrichment/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        order = example.Order(description="Two books")
        example.save_as_alice(order)

    with example.domain.domain_context(current_user="bob"):
        repo = example.domain.repository_for(example.Order)
        saved = repo.get(order.id)
        assert (saved.created_by, saved.updated_by) == ("alice", "alice")

        saved.description = "Three books"
        repo.add(saved)
        updated = repo.get(order.id)

    assert (updated.created_by, updated.updated_by) == ("alice", "bob")
