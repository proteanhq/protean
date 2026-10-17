"""Run the examples on ``docs/patterns/designing-for-concurrent-event-processing.md``."""

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _deliver(handler, events):
    """Hand each event to ``handler`` the way the server does, in order."""
    for event in events:
        handler._handle(event)


def _created(example):
    return example.HubspotClientCreated(hubspot_id="h1", name="Acme")


def _association(example, contacts=("c1", "c2")):
    return example.HubspotAssociationChanged(hubspot_id="h1", contacts=list(contacts))


def _client_state(example):
    repo = example.domain.repository_for(example.Client)
    clients = repo.query.filter(hubspot_id="h1").all().items
    assert len(clients) == 1
    return clients[0].name, clients[0].contacts


def _run_single_handler(order):
    example = load_example("patterns/designing-for-concurrent-event-processing/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        events = [_created(example), _association(example)]
        if order == "reversed":
            events.reverse()
        _deliver(example.HubspotClientHandler, events)
        return _client_state(example)


def _run_process_manager(order):
    example = load_example("patterns/designing-for-concurrent-event-processing/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        events = [_created(example), _association(example)]
        if order == "reversed":
            events.reverse()
        _deliver(example.HubspotClientOnboarding, events)
        return _client_state(example)


def test_the_single_handler_creates_then_associates_in_write_order():
    assert _run_single_handler("written") == ("Acme", ["c1", "c2"])


def test_the_single_handler_needs_the_creation_event_first():
    with pytest.raises(ObjectNotFoundError):
        _run_single_handler("reversed")


@pytest.mark.parametrize("order", ["written", "reversed"])
def test_the_process_manager_ends_in_the_same_state_in_either_order(order):
    assert _run_process_manager(order) == ("Acme", ["c1", "c2"])


def test_the_process_manager_buffers_contacts_until_the_client_exists():
    example = load_example("patterns/designing-for-concurrent-event-processing/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        _deliver(example.HubspotClientOnboarding, [_association(example)])

        repo = example.domain.repository_for(example.Client)
        assert repo.query.filter(hubspot_id="h1").count() == 0


def _unique_key_example():
    example = load_example("patterns/designing-for-concurrent-event-processing/003.py")
    example.domain.init(traverse=False)
    return example


def test_a_redelivered_creation_event_leaves_one_client():
    example = _unique_key_example()
    with example.domain.domain_context():
        _deliver(
            example.HubspotClientHandler,
            [_created(example), _created(example), _association(example)],
        )

        assert _client_state(example) == ("Acme", ["c1", "c2"])


def test_the_unique_key_rejects_a_racing_second_create(monkeypatch):
    example = _unique_key_example()
    # Both runs pass the existence check, as two concurrent runs would.
    monkeypatch.setattr(
        example.ClientRepository, "exists_for", lambda self, hubspot_id: False
    )
    with example.domain.domain_context():
        _deliver(example.HubspotClientHandler, [_created(example)])

        with pytest.raises(ValidationError) as exc_info:
            _deliver(example.HubspotClientHandler, [_created(example)])

        assert "hubspot_id" in exc_info.value.messages
        repo = example.domain.repository_for(example.Client)
        assert repo.query.filter(hubspot_id="h1").count() == 1


def test_an_early_association_event_fails_until_the_client_exists():
    example = _unique_key_example()
    with example.domain.domain_context():
        with pytest.raises(ObjectNotFoundError):
            _deliver(example.HubspotClientHandler, [_association(example)])

        _deliver(
            example.HubspotClientHandler,
            [_created(example), _association(example)],
        )

        assert _client_state(example) == ("Acme", ["c1", "c2"])
