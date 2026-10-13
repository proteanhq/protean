"""An integer identity on SQLite: the column mapping, and the init-time refusal
of the ``uuid`` strategy, whose 128-bit integers no SQL integer column holds."""

import itertools
from typing import Annotated

import pytest
from pydantic import Field as PydanticField
from sqlalchemy import Integer

from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.exceptions import ConfigurationError
from protean.fields import Auto, Identifier, String

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

        assert type(column.type) is Integer
        assert not hasattr(column.type, "length")

    def test_an_aggregate_saves_and_loads_back(self, domain):
        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)
        with domain.domain_context():
            repo = domain.repository_for(Tiny)
            provider = domain.providers["default"]
            repo._dao
            provider._metadata.create_all(provider._engine)

            tiny = Tiny(title="first")
            repo.add(tiny)
            loaded = repo.get(tiny.id)

        assert int(loaded.id) == int(tiny.id)
        assert loaded.title == "first"


def _assert_refused(exc, aggregate_name, provider_name="default"):
    message = str(exc.value)
    assert f"`{aggregate_name}`" in message
    assert f"provider `{provider_name}` (sqlite)" in message
    assert 'identity_strategy = "function"' in message
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


@pytest.mark.sqlite
class TestIntegerIdentityThatInitAccepts:
    def test_an_increment_identifier(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, increment=True)

        domain.init(traverse=False)

    def test_a_field_that_overrides_the_type_to_string(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Auto(identifier=True, identity_type="string")

        domain.init(traverse=False)

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

    def test_an_identifier_with_its_own_default(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            ticket_id: Identifier(identifier=True, default="1")

        domain.init(traverse=False)

    def test_a_string_identifier_the_caller_fills(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            code: String(identifier=True, max_length=20)

        domain.init(traverse=False)

    def test_an_identifier_declared_with_a_plain_pydantic_field(self):
        domain = sqlite_domain(identity_type="integer")

        @domain.aggregate
        class Ticket(BaseAggregate):
            code: Annotated[str, PydanticField(json_schema_extra={"identifier": True})]

        domain.init(traverse=False)

    @pytest.mark.parametrize("identity_type", ["string", "uuid"])
    def test_a_non_integer_domain_identity(self, identity_type):
        domain = sqlite_domain(identity_type=identity_type)

        @domain.aggregate
        class Tiny(BaseAggregate):
            title: String(max_length=50)

        domain.init(traverse=False)
