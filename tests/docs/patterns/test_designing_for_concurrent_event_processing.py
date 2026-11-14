"""Run the examples on ``docs/patterns/designing-for-concurrent-event-processing.md``."""

import re

import pytest

from protean.exceptions import ObjectNotFoundError, ValidationError
from protean.utils.eventing import Message
from tests.docs.support import DOCS, load_example

pytestmark = pytest.mark.no_test_domain

PAGE = DOCS / "patterns/designing-for-concurrent-event-processing.md"
SOLUTION_C_ANCHOR = "solution-c-idempotent-retry-with-unique-constraints"


def _deliver(handler, events):
    """Hand each event to ``handler`` as a ``Message``, the way the server does."""
    for event in events:
        handler._handle(Message.from_domain_object(event))


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


def test_the_single_handler_rejects_a_redelivered_creation_event():
    example = load_example("patterns/designing-for-concurrent-event-processing/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        _deliver(example.HubspotClientHandler, [_created(example)])

        with pytest.raises(ValidationError) as exc_info:
            _deliver(example.HubspotClientHandler, [_created(example)])

        assert "hubspot_id" in exc_info.value.messages
        repo = example.domain.repository_for(example.Client)
        assert repo.query.filter(hubspot_id="h1").count() == 1


@pytest.mark.parametrize("order", ["written", "reversed"])
def test_the_process_manager_ends_in_the_same_state_in_either_order(order):
    assert _run_process_manager(order) == ("Acme", ["c1", "c2"])


def test_a_repeated_creation_event_creates_one_client():
    example = load_example("patterns/designing-for-concurrent-event-processing/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        _deliver(
            example.HubspotClientOnboarding,
            [_created(example), _association(example), _created(example)],
        )

        assert _client_state(example) == ("Acme", ["c1", "c2"])


def test_a_redelivered_create_client_command_fails_on_the_unique_key():
    example = load_example("patterns/designing-for-concurrent-event-processing/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        example.domain.process(example.CreateClient(hubspot_id="h1", name="Acme"))

        with pytest.raises(ValidationError) as exc_info:
            example.domain.process(example.CreateClient(hubspot_id="h1", name="Acme"))

        assert "hubspot_id" in exc_info.value.messages
        repo = example.domain.repository_for(example.Client)
        assert repo.query.filter(hubspot_id="h1").count() == 1


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


def _page_sections():
    """Map each ``###`` heading on the page to the text under it."""
    sections = {}
    heading = None
    for line in PAGE.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            heading = line.lstrip("#").strip() if line.startswith("### ") else None
            if heading:
                sections[heading] = ""
        elif heading:
            sections[heading] += line + "\n"
    return sections


@pytest.mark.parametrize(
    "solution",
    ["Solution A: Combine into a single handler", "Solution B: Process Manager"],
)
def test_solutions_a_and_b_link_to_solution_c_for_redelivery(solution):
    section = _page_sections()[solution]
    assert f"(#{SOLUTION_C_ANCHOR})" in section
    assert "`ValidationError`" in section


def test_the_solution_c_anchor_matches_its_heading():
    slugs = [
        re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
        for heading in _page_sections()
    ]
    assert slugs
    assert SOLUTION_C_ANCHOR in slugs
