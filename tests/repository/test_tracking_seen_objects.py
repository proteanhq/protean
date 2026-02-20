import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.fields import HasMany, Integer, Reference, String


class User(BaseAggregate):
    name: String()


class Client(BaseAggregate):
    name: String(required=True, max_length=100)
    contacts = HasMany("tests.repository.test_tracking_seen_objects.Contact")


class Contact(BaseEntity):
    email: String(required=True, max_length=200)
    is_active: Integer(default=1)

    client = Reference(Client)


class ClientContactAdded(BaseEvent):
    contact_email: String()

    class Meta:
        part_of = Client


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Client)
    test_domain.register(Contact, part_of=Client)
    test_domain.register(ClientContactAdded, part_of=Client)
    test_domain.init(traverse=False)


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestTrackingSeenObjects:
    def test_tracking_aggregate_on_add(self, test_domain):
        uow = UnitOfWork()
        uow.start()

        test_domain.repository_for(User).add(User(name="John Doe"))

        assert len(uow._identity_map) == 1

    def test_tracking_aggregate_on_update(self, test_domain):
        test_domain.repository_for(User).add(User(id="12", name="John Doe"))

        user = test_domain.repository_for(User).get("12")

        uow = UnitOfWork()
        uow.start()

        user.name = "Name Changed"
        test_domain.repository_for(User).add(user)

        assert len(uow._identity_map) == 1
        identifier = next(iter(uow._identity_map["default"]))
        assert uow._identity_map["default"][identifier].name == "Name Changed"

    def test_tracking_aggregate_on_get(self, test_domain):
        test_domain.repository_for(User).add(User(id="12", name="John Doe"))

        uow = UnitOfWork()
        uow.start()

        test_domain.repository_for(User).get("12")

        assert len(uow._identity_map) == 1
        identifier = next(iter(uow._identity_map["default"]))
        assert isinstance(uow._identity_map["default"][identifier], User)

    def test_tracking_aggregate_on_filtering(self, test_domain):
        test_domain.repository_for(User).add(User(id="12", name="John Doe"))
        test_domain.repository_for(User).add(User(id="13", name="Jane Doe"))

        uow = UnitOfWork()
        uow.start()

        test_domain.repository_for(User)._dao.query.filter(name__contains="Doe").all()

        assert len(uow._identity_map["default"]) == 2
        assert all(
            isinstance(item, User) for _, item in uow._identity_map["default"].items()
        )


@pytest.mark.database
@pytest.mark.usefixtures("db")
class TestIdentityMapEventTracking:
    """Tests that aggregates with pending events but no own-field changes
    are still tracked in the identity map so _gather_events picks them up."""

    @pytest.fixture
    def persisted_client(self, test_domain):
        """Create and persist a client, then retrieve to get persisted state."""
        client = Client(name="Acme Corp")
        test_domain.repository_for(Client).add(client)
        return test_domain.repository_for(Client).get(client.id)

    def test_aggregate_with_events_added_to_identity_map(
        self, test_domain, persisted_client
    ):
        """An aggregate that only raised events (no field changes) should
        still appear in the UoW identity map after repository.add()."""
        uow = UnitOfWork()
        uow.start()

        persisted_client.raise_(ClientContactAdded(contact_email="alice@example.com"))

        assert persisted_client.state_.is_persisted
        assert not persisted_client.state_.is_changed
        assert len(persisted_client._events) == 1

        test_domain.repository_for(Client).add(persisted_client)

        assert len(uow._identity_map["default"]) == 1

        events = uow._gather_events()
        event_list = events.get("default", [])
        assert len(event_list) == 1

        uow.rollback()

    def test_aggregate_without_events_not_added_to_identity_map(
        self, test_domain, persisted_client
    ):
        """An aggregate with no events and no field changes should NOT be
        added to the identity map (existing behavior preserved)."""
        uow = UnitOfWork()
        uow.start()

        assert persisted_client.state_.is_persisted
        assert not persisted_client.state_.is_changed
        assert len(persisted_client._events) == 0

        test_domain.repository_for(Client).add(persisted_client)

        assert len(uow._identity_map["default"]) == 0

        uow.rollback()

    def test_new_aggregate_still_persisted_normally(self, test_domain):
        """New aggregates should still go through _dao.save() path."""
        uow = UnitOfWork()
        uow.start()

        client = Client(name="New Corp")
        assert client.state_.is_new

        test_domain.repository_for(Client).add(client)

        assert len(uow._identity_map["default"]) == 1

        uow.rollback()

    def test_changed_aggregate_still_persisted_normally(
        self, test_domain, persisted_client
    ):
        """Changed aggregates should still go through _dao.save() path."""
        uow = UnitOfWork()
        uow.start()

        persisted_client.name = "Updated Corp"
        assert persisted_client.state_.is_changed

        test_domain.repository_for(Client).add(persisted_client)

        assert len(uow._identity_map["default"]) == 1

        uow.rollback()

    def test_events_gathered_after_child_add_and_raise(
        self, test_domain, persisted_client
    ):
        """Simulate the real scenario: add child via HasMany, raise event,
        then ensure events are gathered in UoW."""
        uow = UnitOfWork()
        uow.start()

        contact = Contact(email="bob@example.com")
        persisted_client.add_contacts(contact)

        persisted_client.raise_(ClientContactAdded(contact_email="bob@example.com"))

        assert not persisted_client.state_.is_changed

        test_domain.repository_for(Client).add(persisted_client)

        events = uow._gather_events()
        event_list = events.get("default", [])
        assert len(event_list) == 1

        uow.rollback()

    def test_multiple_events_all_gathered(self, test_domain, persisted_client):
        """Multiple events raised should all be gathered."""
        uow = UnitOfWork()
        uow.start()

        persisted_client.raise_(ClientContactAdded(contact_email="c1@example.com"))
        persisted_client.raise_(ClientContactAdded(contact_email="c2@example.com"))

        assert len(persisted_client._events) == 2

        test_domain.repository_for(Client).add(persisted_client)

        events = uow._gather_events()
        event_list = events.get("default", [])
        assert len(event_list) == 2

        uow.rollback()
