from unittest.mock import Mock, patch

import pytest

from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from protean.core.aggregate import BaseAggregate
from protean.fields import String


class Person(BaseAggregate):
    name = String(required=True)


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
    mock_create_engine.return_value = mock_engine
    provider._engine = mock_engine

    # Mock metadata methods
    provider._metadata = Mock()

    # Execute
    provider._create_database_artifacts()

    # Assert
    # Verify metadata.create_all was called with engine
    provider._metadata.create_all.assert_called_with(mock_engine)


@patch("protean.adapters.repository.sqlalchemy.create_engine")
def test_drop_database_artifacts_drops_tables(
    mock_create_engine, test_domain, provider
):
    # Setup
    provider.domain = test_domain
    mock_engine = Mock()
    mock_create_engine.return_value = mock_engine
    provider._engine = mock_engine

    # Mock metadata methods
    provider._metadata = Mock()

    # Execute
    provider._drop_database_artifacts()

    # Assert
    # Verify metadata.drop_all was called with engine
    provider._metadata.drop_all.assert_called_with(mock_engine)
    # Verify metadata was cleared
    provider._metadata.clear.assert_called()
