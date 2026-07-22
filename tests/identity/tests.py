import json
from uuid import UUID, uuid4

from protean.fields import String

from .elements import ExplicitIdentity, LineItem, Order, Person


class TestIdentityType:
    def test_string_identity(self, test_domain_with_string_identity):
        person = Person(first_name="John", last_name="Doe")
        assert person.id is not None
        assert isinstance(person.id, str)

    def test_int_identity(self, test_domain_with_int_identity):
        person = Person(first_name="John", last_name="Doe")
        assert person.id is not None
        assert isinstance(person.id, int)

    def test_uuid_identity(self, test_domain_with_uuid_identity):
        person = Person(first_name="John", last_name="Doe")
        assert person.id is not None

        # A uuid identity is a *string* in Python (ADR-0021), not a native
        # uuid.UUID: identities cross a JSON boundary constantly, and a native
        # UUID is not JSON-serializable. It is still a valid UUID.
        assert isinstance(person.id, str)
        assert UUID(person.id)  # raises ValueError if not a valid UUID


class TestUUIDIdentityContract:
    """``identity_type = "uuid"`` yields a UUID *string* on every path (ADR-0021)."""

    def test_auto_injected_uuid_id_is_a_string(self, test_domain_with_uuid_identity):
        person = Person(first_name="John", last_name="Doe")
        assert isinstance(person.id, str)
        assert UUID(person.id)

    def test_to_dict_under_uuid_is_json_serializable(
        self, test_domain_with_uuid_identity
    ):
        # The regression this guards: a native uuid.UUID id makes to_dict() fail
        # json.dumps with "Object of type UUID is not JSON serializable".
        person = Person(first_name="John", last_name="Doe")
        json.dumps(person.to_dict())  # must not raise

    def test_explicit_and_auto_injected_uuid_ids_agree(
        self, test_domain_with_uuid_identity
    ):
        # The auto-injected id and an explicit Auto(identity_type="uuid") must be
        # the same runtime type; their divergence (str vs UUID) was the bug.
        auto = Person(first_name="John", last_name="Doe")
        explicit = ExplicitIdentity(name="widget")
        assert isinstance(auto.id, str)
        assert isinstance(explicit.ref, str)
        assert type(auto.id) is type(explicit.ref)

    def test_decorator_registered_aggregate_uuid_id_is_a_string(
        self, test_domain_with_uuid_identity
    ):
        # A @domain.aggregate-decorated element gets its id from the element
        # metaclass path (distinct from a direct BaseAggregate subclass); pin
        # that it too yields a str under uuid.
        domain = test_domain_with_uuid_identity

        @domain.aggregate
        class Widget:
            name: String(max_length=50)

        domain.init(traverse=False)

        widget = Widget(name="x")
        assert isinstance(widget.id, str)
        assert UUID(widget.id)

    def test_nested_entity_uuid_id_is_a_string(self, test_domain_with_uuid_identity):
        # Entities draw identity from the same generator, so the fix covers them
        # uniformly; pin that a child id under uuid stays a string.
        domain = test_domain_with_uuid_identity
        domain.register(Order)
        domain.register(LineItem, part_of=Order)
        domain.init(traverse=False)

        order = Order(number="O-1", items=[LineItem(product="Widget")])

        assert isinstance(order.id, str)
        assert isinstance(order.items[0].id, str)

    def test_a_provided_uuid_value_is_coerced_to_str(
        self, test_domain_with_uuid_identity
    ):
        # A native UUID reaching the id field (a user-passed value, or an adapter
        # that returns one on load, e.g. SQLAlchemy's GUID type) is coerced to
        # str, so the contract holds on the load path too, not only generation.
        provided = uuid4()
        person = Person(first_name="John", last_name="Doe", id=provided)
        assert isinstance(person.id, str)
        assert person.id == str(provided)

    def test_uuid_identity_round_trips_through_the_repository_as_a_string(
        self, test_domain_with_uuid_identity
    ):
        domain = test_domain_with_uuid_identity
        domain.register(Person)
        domain.init(traverse=False)

        person = Person(first_name="John", last_name="Doe")
        assert isinstance(person.id, str)

        repo = domain.repository_for(Person)
        repo.add(person)
        retrieved = repo.get(person.id)

        assert retrieved.id == person.id
        assert isinstance(retrieved.id, str)
