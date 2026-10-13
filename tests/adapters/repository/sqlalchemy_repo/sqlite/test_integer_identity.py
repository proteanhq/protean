"""An integer identity on SQLite: the column mapping, and the refusal of an
identity the column cannot hold, such as the 128-bit integer the ``uuid``
strategy makes."""

import itertools
from typing import Annotated

import pytest
from pydantic import Field as PydanticField
from sqlalchemy import Column
from sqlalchemy import String as SAString

from protean.core.aggregate import BaseAggregate
from protean.core.database_model import BaseDatabaseModel
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import Auto, HasMany, Identifier, Integer, String
from protean.utils.reflection import id_field

SQLITE = {"provider": "sqlite", "database_uri": "sqlite:///:memory:"}
MEMORY = {"provider": "memory"}

_counter = itertools.count(1)


def next_int() -> int:
    return next(_counter)


def sqlite_domain(identity_function=None, **config) -> Domain:
    databases = config.pop("databases", {"default": SQLITE})
    return Domain(
        name="IntegerIdentity",
        config={"databases": databases, **config},
        identity_function=identity_function,
    )


def round_trip(domain, aggregate_cls, **values):
    """Save a new aggregate and load it back by its id."""
    with domain.domain_context():
        repo = domain.repository_for(aggregate_cls)
        provider = domain.providers["default"]
        repo._dao
        provider._metadata.create_all(provider._engine)

        saved = aggregate_cls(**values)
        repo.add(saved)
        loaded = repo.get(getattr(saved, id_field(aggregate_cls).field_name))
    return saved, loaded


@pytest.mark.sqlite
class TestIntegerIdentityUnderFunctionStrategy:
    @pytest.fixture
    def domain(self):
        domain = sqlite_domain(
            identity_type="integer",
            identity_strategy="function",
            identity_function=next_int,
        )
        return domain

    def test_the_model_builds_with_an_integer_id_column(self, domain):
        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)
        with domain.domain_context():
            dao = domain.repository_for(Tiny)._dao
            column = dao.database_model_cls.__table__.columns["id"]
            dialect = domain.providers["default"]._engine.dialect

        assert column.type.compile(dialect=dialect) == "INTEGER"

    def test_an_aggregate_saves_and_loads_back(self, domain):
        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)
        tiny, loaded = round_trip(domain, Tiny, title="first")

        assert loaded.id == tiny.id
        assert loaded.title == "first"

    def test_a_declared_auto_identifier_saves_and_loads_back(self, domain):
        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True)
            title: String(max_length=50)

        domain.init(traverse=False)
        ticket, loaded = round_trip(domain, Ticket, title="first")

        assert loaded.ticket_id == ticket.ticket_id
        assert loaded.title == "first"


def _assert_refused(exc, element_name, provider_name="default", kind="Aggregate"):
    message = str(exc.value)
    assert f"{kind} `{element_name}`" in message
    assert f"provider `{provider_name}` (sqlite)" in message
    assert 'identity_strategy = "function"' in message
    assert "`identity_function`" in message
    assert "Auto(increment=True)" in message


@pytest.mark.sqlite
class TestIntegerIdentityUnderUuidStrategyIsRefused:
    def test_the_implicit_id_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Tiny")
        assert "no SQL integer column holds it" in str(exc.value)

    def test_an_explicit_auto_identifier_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Ticket")

    def test_the_integer_type_from_the_field_is_refused(self):
        domain = sqlite_domain()  # string identity, uuid strategy

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, identity_type="integer")

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Ticket")
        # The column follows the domain setting, so it is text, not integer.
        assert "no SQL integer column" not in str(exc.value)
        assert 'domain `identity_type` ("string")' in str(exc.value)

    def test_the_uuid_strategy_from_the_field_is_refused(self):
        domain = sqlite_domain(
            identity_type="integer",
            identity_strategy="function",
            identity_function=next_int,
        )

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, identity_strategy="uuid")

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Ticket")

    def test_an_identifier_field_with_no_default_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Identifier(identifier=True)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Ticket")

    def test_only_the_aggregate_on_the_sql_provider_is_refused(self):
        domain = sqlite_domain(
            identity_type="integer",
            databases={"default": MEMORY, "sqlite": SQLITE},
        )

        @domain.aggregate
        class InMemory(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)  # memory holds a 128-bit integer

        @domain.aggregate(provider="sqlite")
        class OnSqlite(BaseAggregate):
            title: String(max_length=50)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "OnSqlite", provider_name="sqlite")
        assert "InMemory" not in str(exc.value)

    def test_an_entity_on_the_domain_strategy_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Order(BaseAggregate):
            order_id: Auto(
                identifier=True,
                identity_strategy="function",
                identity_function=next_int,
            )
            lines: HasMany("Line")

        @domain.entity(part_of=Order)
        class Line(BaseEntity):
            quantity: Integer()

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Line", kind="Entity")

    def test_a_projection_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.projection
        class Board(BaseProjection):
            board_id: Auto(identifier=True)
            title: String(max_length=50)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Board", kind="Projection")

    def test_an_aggregate_registered_after_init_is_refused_on_first_use(self):
        domain = sqlite_domain(identity_type="integer")
        domain.init(traverse=False)

        @domain.aggregate
        class Late(BaseAggregate):
            title: String(max_length=50)

        with domain.domain_context():
            with pytest.raises(ConfigurationError) as exc:
                domain.repository_for(Late)._dao

        _assert_refused(exc, "Late")


@pytest.mark.sqlite
class TestANonIntegerIdentityOnAnIntegerDomainIsRefused:
    @pytest.mark.parametrize("identity_type", ["string", "uuid"])
    def test_a_field_that_overrides_the_type(self, identity_type):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, identity_type=identity_type)

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        message = str(exc.value)
        assert "Aggregate `Ticket`" in message
        assert f"generates a {identity_type} identity" in message
        assert "its column is an integer column" in message


@pytest.mark.sqlite
class TestIntegerIdentityThatSqliteStores:
    def test_an_increment_identifier(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, increment=True)
            title: String(max_length=50)

        domain.init(traverse=False)
        _, loaded = round_trip(domain, Ticket, title="first")

        assert loaded.ticket_id == 1
        assert loaded.title == "first"

    def test_a_field_that_overrides_the_strategy_to_function(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(
                identifier=True,
                identity_strategy="function",
                identity_function=next_int,
            )

        domain.init(traverse=False)
        ticket, loaded = round_trip(domain, Ticket)

        assert loaded.ticket_id == ticket.ticket_id

    def test_an_identifier_with_its_own_default(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Identifier(identifier=True, default="1")

        domain.init(traverse=False)
        _, loaded = round_trip(domain, Ticket)

        assert loaded.ticket_id == "1"

    def test_a_numeric_string_identifier_the_caller_fills(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            code: String(identifier=True, max_length=20)

        domain.init(traverse=False)
        _, loaded = round_trip(domain, Ticket, code="42")

        assert loaded.code == "42"

    def test_an_integer_identifier_declared_with_a_plain_pydantic_field(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            code: Annotated[int, PydanticField(json_schema_extra={"identifier": True})]

        domain.init(traverse=False)
        _, loaded = round_trip(domain, Ticket, code=42)

        assert loaded.code == 42

    @pytest.mark.parametrize("identity_type", ["string", "uuid"])
    def test_a_non_integer_domain_identity(self, identity_type):
        domain = sqlite_domain(identity_type=identity_type)

        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)
        tiny, loaded = round_trip(domain, Tiny, title="first")

        assert str(loaded.id) == str(tiny.id)


@pytest.mark.sqlite
class TestACustomModelThatDeclaresTheIdentityColumn:
    def test_an_integer_identity_under_the_uuid_strategy_is_stored(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True)

        @domain.database_model(part_of=Ticket)
        class TicketModel(BaseDatabaseModel):
            ticket_id = Column(SAString(50), primary_key=True)

        domain.init(traverse=False)
        ticket, loaded = round_trip(domain, Ticket)

        assert loaded.ticket_id == ticket.ticket_id
        assert int(ticket.ticket_id) >= 2**64

    def test_a_field_that_overrides_the_type_is_stored(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, identity_type="string")

        @domain.database_model(part_of=Ticket)
        class TicketModel(BaseDatabaseModel):
            ticket_id = Column(SAString(50), primary_key=True)

        domain.init(traverse=False)
        ticket, loaded = round_trip(domain, Ticket)

        assert loaded.ticket_id == ticket.ticket_id

    def test_a_custom_model_without_the_identity_column_is_refused(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        @domain.database_model(part_of=Tiny)
        class TinyModel(BaseDatabaseModel):
            title = Column(SAString(50))

        with pytest.raises(ConfigurationError) as exc:
            domain.init(traverse=False)

        _assert_refused(exc, "Tiny")


@pytest.mark.sqlite
class TestElementsWithNoSqlTableAreNotChecked:
    def test_an_event_sourced_aggregate(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate(event_sourced=True)
        class Account(BaseAggregate):
            name: String(max_length=50)

        @domain.event(part_of=Account)
        class Opened(BaseEvent):
            name: String(max_length=50)

        domain.init(traverse=False)

    def test_an_abstract_aggregate(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate(abstract=True)
        class Base(BaseAggregate):
            name: String(max_length=50)

        domain.init(traverse=False)
