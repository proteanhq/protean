from unittest.mock import Mock, patch

import pytest

from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.core.aggregate import BaseAggregate
from protean.core.entity import BaseEntity
from protean.fields import HasMany, String


class Person(BaseAggregate):
    name: String(required=True)


@pytest.fixture
def provider(test_domain):
    provider = PostgresqlProvider(
        domain=test_domain, name="default", conn_info={"database_uri": "sqlite://"}
    )
    return provider


@patch("protean.adapters.repository.sqlalchemy.create_engine")
def test_create_database_artifacts_creates_tables(
    mock_create_engine, test_domain, provider
):
    # Setup
    provider.domain = test_domain
    mock_engine = Mock()
    mock_connection = Mock()
    mock_engine.connect.return_value = mock_connection
    mock_create_engine.return_value = mock_engine
    provider._engine = mock_engine

    # Mock metadata methods
    provider._metadata = Mock()

    # Execute
    provider._create_database_artifacts()

    # Assert
    # Verify engine.connect was called
    mock_engine.connect.assert_called()
    # Verify metadata.create_all was called with connection
    provider._metadata.create_all.assert_called_with(mock_connection)
    # Verify connection.close was called
    mock_connection.close.assert_called()


@patch("protean.adapters.repository.sqlalchemy.create_engine")
def test_drop_database_artifacts_drops_tables(
    mock_create_engine, test_domain, provider
):
    # Setup
    provider.domain = test_domain
    mock_engine = Mock()
    mock_connection = Mock()
    mock_engine.connect.return_value = mock_connection
    mock_create_engine.return_value = mock_engine
    provider._engine = mock_engine

    # Mock metadata methods
    provider._metadata = Mock()

    # Execute
    provider._drop_database_artifacts()

    # Assert
    # Verify engine.connect was called
    mock_engine.connect.assert_called()
    # Verify metadata.drop_all was called with connection
    provider._metadata.drop_all.assert_called_with(mock_connection)
    # Verify connection.close was called
    mock_connection.close.assert_called()
    # Verify metadata was cleared
    provider._metadata.clear.assert_called()


class ESOrder(BaseAggregate):
    name: String(required=True)
    items = HasMany("ESLineItem")


class ESLineItem(BaseEntity):
    sku: String(required=True)


@pytest.mark.no_test_domain
def test_create_artifacts_skips_event_sourced_aggregates():
    """Event-sourced aggregates use the event store, not SQL tables.
    _create_database_artifacts should skip them and their child entities."""
    from protean import Domain

    domain = Domain(__file__, "ES-Test")

    # Register a regular aggregate so repository_for is called for it
    domain.register(Person)

    # Register an event-sourced aggregate and its entity
    domain.register(ESOrder, is_event_sourced=True)
    domain.register(ESLineItem, part_of=ESOrder)
    domain.init(traverse=False)

    provider = PostgresqlProvider(
        domain=domain, name="default", conn_info={"database_uri": "sqlite://"}
    )

    # Track which classes repository_for is called with
    called_classes: list[type] = []
    original_repo_for = domain.repository_for

    def tracking_repo_for(cls):
        called_classes.append(cls)
        return original_repo_for(cls)

    domain.repository_for = tracking_repo_for

    mock_engine = Mock()
    mock_connection = Mock()
    mock_engine.connect.return_value = mock_connection
    provider._engine = mock_engine
    provider._metadata = Mock()

    provider._create_database_artifacts()

    # Person (regular aggregate) should be processed
    assert Person in called_classes
    # Event-sourced aggregate and its entity should be skipped
    assert ESOrder not in called_classes
    assert ESLineItem not in called_classes
