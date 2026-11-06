"""The SQLAlchemy provider's public ``metadata`` property.

It holds the table of every element the provider owns, builds that list on read
without touching the database, and puts the tables back after a drop.
"""

import pytest
from sqlalchemy import MetaData, inspect

from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.domain import Domain
from protean.fields import HasMany, Identifier, Integer, String
from tests.shared import POSTGRES_URI


class Person(BaseAggregate):
    name: String(required=True)
    addresses = HasMany("Address")


class Address(BaseEntity):
    street: String(required=True)


class PersonSummary(BaseProjection):
    person_id: Identifier(identifier=True)
    name: String()


class Ledger(BaseAggregate):
    balance: Integer(default=0)


class Leaderboard(BaseProjection):
    entry_id: Identifier(identifier=True)
    score: Integer()


class Invoice(BaseAggregate):
    number: String(required=True)


class AbstractRecord(BaseAggregate):
    created_by: String()


class PersonRenamed(BaseEvent):
    person_id: Identifier()


class PersonSummaryProjector(BaseProjector):
    @on(PersonRenamed)
    def on_person_renamed(self, event: PersonRenamed) -> None:
        pass


ELEMENT_TABLES = {"person", "address", "person_summary"}


def _domain(
    *,
    outbox: bool = False,
    idempotent_projector: bool = False,
    default_managed: bool = True,
) -> Domain:
    domain = Domain(name="ProviderMetadata")
    domain.config["databases"]["default"] = {
        "provider": "sqlite",
        "database_uri": "sqlite:///:memory:",
    }
    if not default_managed:
        domain.config["databases"]["default"]["managed"] = False
    if outbox:
        domain.config["enable_outbox"] = True
        domain.config["server"] = {"default_subscription_type": "stream"}

    domain.register(Person)
    domain.register(Address, part_of=Person)
    domain.register(PersonSummary)
    if idempotent_projector:
        domain.register(PersonRenamed, part_of=Person)
        domain.register(
            PersonSummaryProjector,
            projector_for=PersonSummary,
            aggregates=[Person],
            idempotent=True,
        )
    domain.init(traverse=False)
    return domain


def _table_names(metadata: MetaData) -> set[str]:
    return {table.name for table in metadata.tables.values()}


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestMetadataContents:
    def test_holds_only_tables_of_owned_elements(self):
        domain = Domain(name="ProviderMetadataOwned")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:///:memory:",
        }
        domain.config["databases"]["other"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:///:memory:",
        }
        domain.register(Person)
        domain.register(Address, part_of=Person)
        domain.register(PersonSummary)
        domain.register(Ledger, event_sourced=True)
        domain.register(Leaderboard, cache="default")
        domain.register(Invoice, provider="other")
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            # No repository has been touched, so the read builds the list.
            assert provider._metadata.tables == {}

            assert _table_names(provider.metadata) == ELEMENT_TABLES
            assert _table_names(domain.providers["other"].metadata) == {"invoice"}

    def test_two_reads_return_the_same_tables_and_object(self):
        domain = _domain()
        with domain.domain_context():
            provider = domain.providers["default"]
            first = _table_names(provider.metadata)
            second_metadata = provider.metadata

            assert first == ELEMENT_TABLES
            assert _table_names(second_metadata) == ELEMENT_TABLES
            assert second_metadata is provider._metadata

    def test_holds_no_table_for_an_abstract_aggregate(self):
        domain = Domain(name="ProviderMetadataAbstract")
        domain.config["databases"]["default"] = {
            "provider": "sqlite",
            "database_uri": "sqlite:///:memory:",
        }
        domain.register(AbstractRecord, abstract=True)
        domain.register(Person)
        domain.register(Address, part_of=Person)
        domain.register(PersonSummary)
        domain.init(traverse=False)

        with domain.domain_context():
            provider = domain.providers["default"]
            assert _table_names(provider.metadata) == ELEMENT_TABLES

            domain.setup_database()
            assert set(inspect(provider._engine).get_table_names()) == (ELEMENT_TABLES)

    def test_holds_outbox_table_when_outbox_is_enabled(self):
        domain = _domain(outbox=True)
        with domain.domain_context():
            names = _table_names(domain.providers["default"].metadata)

        assert names == ELEMENT_TABLES | {"outbox"}

    def test_holds_processed_message_table_for_idempotent_projector(self):
        domain = _domain(idempotent_projector=True)
        with domain.domain_context():
            names = _table_names(domain.providers["default"].metadata)

        assert names == ELEMENT_TABLES | {"processed_message"}

    def test_holds_neither_framework_table_by_default(self):
        domain = _domain()
        with domain.domain_context():
            names = _table_names(domain.providers["default"].metadata)

        assert names == ELEMENT_TABLES

    def test_unmanaged_provider_holds_no_outbox_table(self):
        domain = _domain(outbox=True, default_managed=False)
        with domain.domain_context():
            names = _table_names(domain.providers["default"].metadata)

        assert names == ELEMENT_TABLES


@pytest.mark.sqlite
@pytest.mark.no_test_domain
class TestMetadataAfterDrop:
    def test_drop_then_read_holds_the_same_tables_and_setup_recreates_them(self):
        domain = _domain(outbox=True)
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.setup_database()
            before = _table_names(provider.metadata)
            assert before == ELEMENT_TABLES | {"outbox"}
            assert set(inspect(provider._engine).get_table_names()) == before

            domain.drop_database()
            assert inspect(provider._engine).get_table_names() == []
            assert _table_names(provider.metadata) == before

            domain.setup_database()
            assert set(inspect(provider._engine).get_table_names()) == before

    def test_setup_after_drop_recreates_tables_without_a_read(self):
        domain = _domain(outbox=True)
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.setup_database()
            domain.drop_database()

            domain.setup_database()

            assert set(inspect(provider._engine).get_table_names()) == (
                ELEMENT_TABLES | {"outbox"}
            )

    def test_data_reset_after_drop_raises_nothing(self):
        domain = _domain(outbox=True)
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.setup_database()
            domain.drop_database()

            # The order the ``db`` fixture teardown uses: no read in between.
            provider._data_reset()

    def test_data_reset_after_drop_read_and_setup_raises_nothing(self):
        domain = _domain(outbox=True)
        with domain.domain_context():
            provider = domain.providers["default"]
            domain.setup_database()
            domain.drop_database()

            assert _table_names(provider.metadata) == ELEMENT_TABLES | {"outbox"}
            # The read puts the dropped tables back into the metadata, so
            # ``_data_reset()`` needs them to exist in the database again.
            domain.setup_database()
            provider._data_reset()


@pytest.mark.postgresql
@pytest.mark.no_test_domain
def test_tables_take_the_configured_schema():
    domain = Domain(name="ProviderMetadataSchema")
    domain.config["databases"]["default"] = {
        "provider": "postgresql",
        "database_uri": POSTGRES_URI,
        "schema": "custom",
    }
    domain.config["enable_outbox"] = True
    domain.config["server"] = {"default_subscription_type": "stream"}
    domain.register(Person)
    domain.register(Address, part_of=Person)
    domain.register(PersonSummary)
    domain.init(traverse=False)

    with domain.domain_context():
        provider = domain.providers["default"]
        try:
            tables = list(provider.metadata.tables.values())

            assert {table.name for table in tables} == ELEMENT_TABLES | {"outbox"}
            assert all(table.schema == "custom" for table in tables)
        finally:
            provider.close()
