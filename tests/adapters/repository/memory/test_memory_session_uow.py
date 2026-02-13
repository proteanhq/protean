"""Test Memory Session and Unit of Work integration"""

import pytest

from protean import UnitOfWork
from protean.core.aggregate import _LegacyBaseAggregate as BaseAggregate
from protean.fields import String, Integer


class Product(BaseAggregate):
    name = String(max_length=100, required=True)
    price = Integer()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Product)


def test_memory_session_uses_existing_uow_session(test_domain):
    """Test that MemorySession reuses existing UoW session"""
    with UnitOfWork():
        # Create a product within UoW
        product = Product(name="Laptop", price=1000)
        test_domain.repository_for(Product).add(product)

        # Get the provider and create a new session
        provider = test_domain.providers["default"]

        # The first session should be stored in UoW
        first_session = provider.get_session()

        # A new session request should reuse the existing UoW session database
        second_session = provider.get_session()

        # Both sessions should share the same database reference
        assert first_session._db is second_session._db

        # Verify the product is accessible in both sessions
        schema_name = (
            "product"  # Schema name derived from class name Product -> product
        )
        product_data = first_session._db["data"].get(schema_name, {})
        assert len(product_data) == 1
        assert list(product_data.values())[0]["name"] == "Laptop"

        # Same data should be accessible through second session
        product_data_2 = second_session._db["data"].get(schema_name, {})
        assert product_data is product_data_2


def test_memory_session_commit_updates_uow_session(test_domain):
    """Test that MemorySession.commit updates UoW session data"""
    with UnitOfWork() as uow:
        # Create initial product
        product1 = Product(name="Mouse", price=25)
        test_domain.repository_for(Product).add(product1)

        provider = test_domain.providers["default"]
        session = provider.get_session()

        # Modify data in the session
        schema_name = "product"
        product_id = list(session._db["data"][schema_name].keys())[0]
        session._db["data"][schema_name][product_id]["price"] = 30

        # Commit should update the UoW session data
        session.commit()

        # Verify the UoW session has the updated data
        uow_session = uow._sessions[provider.name]
        assert uow_session._db["data"][schema_name][product_id]["price"] == 30


def test_memory_session_new_connection_bypasses_uow(test_domain):
    """Test that new_connection=True bypasses UoW session sharing"""
    with UnitOfWork():
        # Create a product within UoW
        product = Product(name="Keyboard", price=50)
        test_domain.repository_for(Product).add(product)

        provider = test_domain.providers["default"]

        # Get a new connection that should bypass UoW
        new_conn = provider.get_connection()

        # This connection should have its own database copy
        regular_session = provider.get_session()

        # They should have different database references
        assert new_conn._db is not regular_session._db

        # New connection should have empty data (gets copy of provider._databases)
        # Regular session should have the data created within UoW
        schema_name = "product"
        assert (
            len(new_conn._db["data"].get(schema_name, {})) == 0
        )  # No data in provider._databases yet
        assert (
            len(regular_session._db["data"].get(schema_name, {})) == 1
        )  # Data in UoW session


def test_memory_session_commit_without_uow(test_domain):
    """Test that MemorySession.commit works when no UoW is active"""
    # Create a product without UoW
    product = Product(name="Monitor", price=200)
    test_domain.repository_for(Product).add(product)

    provider = test_domain.providers["default"]
    session = provider.get_session()

    # Modify data in the session
    schema_name = "product"
    product_id = list(session._db["data"][schema_name].keys())[0]
    session._db["data"][schema_name][product_id]["price"] = 250

    # Commit should update the provider's database directly
    session.commit()

    # Verify the provider's database has the updated data
    assert provider._databases[schema_name][product_id]["price"] == 250

    # Create a new session and verify it sees the updated data
    new_session = provider.get_session()
    assert new_session._db["data"][schema_name][product_id]["price"] == 250


def test_memory_session_isolation_with_multiple_providers(test_domain):
    """Test that sessions are properly isolated per provider"""
    # Add a second provider for testing
    if not hasattr(test_domain, "config") or "databases" not in test_domain.config:
        pytest.skip("Test domain doesn't support multiple databases")

    test_domain.config["databases"]["secondary"] = {"provider": "memory"}
    test_domain._initialize()

    with UnitOfWork() as uow:
        # Create products using different providers
        product1 = Product(name="Product1", price=100)
        test_domain.repository_for(Product).add(product1)

        # Get sessions through UnitOfWork to ensure they are registered
        default_session = uow.get_session("default")
        secondary_session = uow.get_session("secondary")

        # Sessions should have separate databases
        assert default_session._db is not secondary_session._db

        # Only default should have the product
        schema_name = "product"
        assert len(default_session._db["data"].get(schema_name, {})) == 1
        assert len(secondary_session._db["data"].get(schema_name, {})) == 0

        # Verify UoW tracks both sessions separately
        assert "default" in uow._sessions
        assert "secondary" in uow._sessions
        assert uow._sessions["default"] is not uow._sessions["secondary"]
