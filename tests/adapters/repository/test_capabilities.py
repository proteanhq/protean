import pytest

from protean.port.provider import DatabaseCapabilities


class TestDatabaseCapabilities:
    """Test suite for DatabaseCapabilities flag algebra."""

    def test_individual_capabilities_are_truthy(self):
        """Test that individual capability flags are truthy."""
        assert DatabaseCapabilities.CRUD
        assert DatabaseCapabilities.FILTER
        assert DatabaseCapabilities.BULK_OPERATIONS
        assert DatabaseCapabilities.ORDERING
        assert DatabaseCapabilities.TRANSACTIONS
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS
        assert DatabaseCapabilities.OPTIMISTIC_LOCKING
        assert DatabaseCapabilities.RAW_QUERIES
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT
        assert DatabaseCapabilities.CONNECTION_POOLING
        assert DatabaseCapabilities.NATIVE_JSON
        assert DatabaseCapabilities.NATIVE_ARRAY

    def test_capability_combination(self):
        """Test combining capabilities using bitwise operations."""
        combined = DatabaseCapabilities.CRUD | DatabaseCapabilities.FILTER
        assert DatabaseCapabilities.CRUD in combined
        assert DatabaseCapabilities.FILTER in combined
        assert DatabaseCapabilities.TRANSACTIONS not in combined

    def test_basic_storage_capability_set(self):
        """Test BASIC_STORAGE contains expected individual flags."""
        caps = DatabaseCapabilities.BASIC_STORAGE
        assert DatabaseCapabilities.CRUD in caps
        assert DatabaseCapabilities.FILTER in caps
        assert DatabaseCapabilities.BULK_OPERATIONS in caps
        assert DatabaseCapabilities.ORDERING in caps

        # Should not include higher-tier capabilities
        assert DatabaseCapabilities.TRANSACTIONS not in caps
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS not in caps
        assert DatabaseCapabilities.RAW_QUERIES not in caps
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT not in caps

    def test_relational_capability_set(self):
        """Test RELATIONAL contains expected flags."""
        caps = DatabaseCapabilities.RELATIONAL
        # BASIC_STORAGE flags
        assert DatabaseCapabilities.CRUD in caps
        assert DatabaseCapabilities.FILTER in caps
        assert DatabaseCapabilities.BULK_OPERATIONS in caps
        assert DatabaseCapabilities.ORDERING in caps
        # Additional relational flags
        assert DatabaseCapabilities.TRANSACTIONS in caps
        assert DatabaseCapabilities.OPTIMISTIC_LOCKING in caps
        assert DatabaseCapabilities.RAW_QUERIES in caps
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT in caps
        assert DatabaseCapabilities.CONNECTION_POOLING in caps

        # Should NOT include
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS not in caps
        assert DatabaseCapabilities.NATIVE_JSON not in caps
        assert DatabaseCapabilities.NATIVE_ARRAY not in caps

    def test_document_store_capability_set(self):
        """Test DOCUMENT_STORE contains expected flags."""
        caps = DatabaseCapabilities.DOCUMENT_STORE
        # BASIC_STORAGE flags
        assert DatabaseCapabilities.CRUD in caps
        assert DatabaseCapabilities.FILTER in caps
        assert DatabaseCapabilities.BULK_OPERATIONS in caps
        assert DatabaseCapabilities.ORDERING in caps
        # Additional document store flags
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT in caps
        assert DatabaseCapabilities.OPTIMISTIC_LOCKING in caps

        # Should NOT include
        assert DatabaseCapabilities.TRANSACTIONS not in caps
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS not in caps
        assert DatabaseCapabilities.RAW_QUERIES not in caps
        assert DatabaseCapabilities.CONNECTION_POOLING not in caps

    def test_in_memory_capability_set(self):
        """Test IN_MEMORY contains expected flags."""
        caps = DatabaseCapabilities.IN_MEMORY
        # BASIC_STORAGE flags
        assert DatabaseCapabilities.CRUD in caps
        assert DatabaseCapabilities.FILTER in caps
        assert DatabaseCapabilities.BULK_OPERATIONS in caps
        assert DatabaseCapabilities.ORDERING in caps
        # Additional in-memory flags
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS in caps
        assert DatabaseCapabilities.OPTIMISTIC_LOCKING in caps
        assert DatabaseCapabilities.RAW_QUERIES in caps

        # Should NOT include
        assert DatabaseCapabilities.TRANSACTIONS not in caps
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT not in caps
        assert DatabaseCapabilities.CONNECTION_POOLING not in caps

    def test_convenience_set_completeness(self):
        """Test that convenience sets equal their explicit flag combinations."""
        assert DatabaseCapabilities.BASIC_STORAGE == (
            DatabaseCapabilities.CRUD
            | DatabaseCapabilities.FILTER
            | DatabaseCapabilities.BULK_OPERATIONS
            | DatabaseCapabilities.ORDERING
        )

        assert DatabaseCapabilities.RELATIONAL == (
            DatabaseCapabilities.BASIC_STORAGE
            | DatabaseCapabilities.TRANSACTIONS
            | DatabaseCapabilities.OPTIMISTIC_LOCKING
            | DatabaseCapabilities.RAW_QUERIES
            | DatabaseCapabilities.SCHEMA_MANAGEMENT
            | DatabaseCapabilities.CONNECTION_POOLING
        )

        assert DatabaseCapabilities.DOCUMENT_STORE == (
            DatabaseCapabilities.BASIC_STORAGE
            | DatabaseCapabilities.SCHEMA_MANAGEMENT
            | DatabaseCapabilities.OPTIMISTIC_LOCKING
        )

        assert DatabaseCapabilities.IN_MEMORY == (
            DatabaseCapabilities.BASIC_STORAGE
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
            | DatabaseCapabilities.OPTIMISTIC_LOCKING
            | DatabaseCapabilities.RAW_QUERIES
        )

    def test_basic_storage_is_subset_of_relational(self):
        """Test that RELATIONAL includes all BASIC_STORAGE flags."""
        basic = DatabaseCapabilities.BASIC_STORAGE
        relational = DatabaseCapabilities.RELATIONAL
        assert (relational & basic) == basic

    def test_basic_storage_is_subset_of_document_store(self):
        """Test that DOCUMENT_STORE includes all BASIC_STORAGE flags."""
        basic = DatabaseCapabilities.BASIC_STORAGE
        document = DatabaseCapabilities.DOCUMENT_STORE
        assert (document & basic) == basic

    def test_basic_storage_is_subset_of_in_memory(self):
        """Test that IN_MEMORY includes all BASIC_STORAGE flags."""
        basic = DatabaseCapabilities.BASIC_STORAGE
        in_memory = DatabaseCapabilities.IN_MEMORY
        assert (in_memory & basic) == basic

    def test_capability_subtraction(self):
        """Test removing capabilities from a set."""
        relational = DatabaseCapabilities.RELATIONAL
        without_transactions = relational & ~DatabaseCapabilities.TRANSACTIONS

        assert DatabaseCapabilities.CRUD in without_transactions
        assert DatabaseCapabilities.TRANSACTIONS not in without_transactions
        assert DatabaseCapabilities.RAW_QUERIES in without_transactions

    def test_orthogonal_capabilities(self):
        """Test that database capabilities are orthogonal (not strictly hierarchical).

        Unlike broker capabilities, DOCUMENT_STORE has SCHEMA_MANAGEMENT
        but not TRANSACTIONS, while IN_MEMORY has neither SCHEMA_MANAGEMENT
        nor TRANSACTIONS (real).
        """
        document = DatabaseCapabilities.DOCUMENT_STORE
        in_memory = DatabaseCapabilities.IN_MEMORY

        # DOCUMENT_STORE has SCHEMA_MANAGEMENT, IN_MEMORY does not
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT in document
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT not in in_memory

        # IN_MEMORY has RAW_QUERIES, DOCUMENT_STORE does not
        assert DatabaseCapabilities.RAW_QUERIES in in_memory
        assert DatabaseCapabilities.RAW_QUERIES not in document

        # Neither is a subset of the other
        assert (document & in_memory) != document
        assert (document & in_memory) != in_memory

    def test_capability_union(self):
        """Test union of two capability sets."""
        combined = (
            DatabaseCapabilities.RELATIONAL
            | DatabaseCapabilities.NATIVE_JSON
            | DatabaseCapabilities.NATIVE_ARRAY
        )
        assert DatabaseCapabilities.TRANSACTIONS in combined
        assert DatabaseCapabilities.NATIVE_JSON in combined
        assert DatabaseCapabilities.NATIVE_ARRAY in combined

    def test_capability_intersection(self):
        """Test intersection of two capability sets."""
        relational = DatabaseCapabilities.RELATIONAL
        document = DatabaseCapabilities.DOCUMENT_STORE

        common = relational & document
        # Both have BASIC_STORAGE + SCHEMA_MANAGEMENT + OPTIMISTIC_LOCKING
        assert DatabaseCapabilities.CRUD in common
        assert DatabaseCapabilities.SCHEMA_MANAGEMENT in common
        assert DatabaseCapabilities.OPTIMISTIC_LOCKING in common
        # TRANSACTIONS only in relational
        assert DatabaseCapabilities.TRANSACTIONS not in common

    def test_capability_checking_methods(self):
        """Test static capability checking logic (mirrors broker test)."""
        in_memory = DatabaseCapabilities.IN_MEMORY

        # has single capability
        assert DatabaseCapabilities.CRUD in in_memory
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS in in_memory
        assert DatabaseCapabilities.TRANSACTIONS not in in_memory

        # has all
        basic = DatabaseCapabilities.CRUD | DatabaseCapabilities.FILTER
        assert (in_memory & basic) == basic

        # has any
        mixed = (
            DatabaseCapabilities.TRANSACTIONS
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
        )
        assert bool(in_memory & mixed)

        # does not have all of mixed
        assert (in_memory & mixed) != mixed


class TestDatabaseCapabilityMethods:
    """Test capability checking methods on actual provider instances."""

    def test_memory_provider_capabilities(self, test_domain):
        """Test MemoryProvider capability declaration and methods."""
        provider = test_domain.providers["default"]

        if provider.__class__.__name__ != "MemoryProvider":
            pytest.skip("Test specific to MemoryProvider")

        assert provider.capabilities == DatabaseCapabilities.IN_MEMORY

        # Has BASIC_STORAGE capabilities
        assert provider.has_capability(DatabaseCapabilities.CRUD)
        assert provider.has_capability(DatabaseCapabilities.FILTER)
        assert provider.has_capability(DatabaseCapabilities.BULK_OPERATIONS)
        assert provider.has_capability(DatabaseCapabilities.ORDERING)

        # Has SIMULATED_TRANSACTIONS but not TRANSACTIONS
        assert provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)
        assert not provider.has_capability(DatabaseCapabilities.TRANSACTIONS)

        # Has OPTIMISTIC_LOCKING and RAW_QUERIES
        assert provider.has_capability(DatabaseCapabilities.OPTIMISTIC_LOCKING)
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)

        # Does not have SCHEMA_MANAGEMENT or CONNECTION_POOLING
        assert not provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert not provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)

        # Does not have type system capabilities
        assert not provider.has_capability(DatabaseCapabilities.NATIVE_JSON)
        assert not provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY)

    def test_postgresql_provider_capabilities(self, test_domain):
        """Test PostgresqlProvider capability declaration and methods."""
        provider = test_domain.providers["default"]

        if provider.__class__.__name__ != "PostgresqlProvider":
            pytest.skip("Test specific to PostgresqlProvider")

        expected = (
            DatabaseCapabilities.RELATIONAL
            | DatabaseCapabilities.NATIVE_JSON
            | DatabaseCapabilities.NATIVE_ARRAY
        )
        assert provider.capabilities == expected

        assert provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert provider.has_capability(DatabaseCapabilities.NATIVE_JSON)
        assert provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)
        assert provider.has_capability(DatabaseCapabilities.OPTIMISTIC_LOCKING)

        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)

    def test_sqlite_provider_capabilities(self, test_domain):
        """Test SqliteProvider capability declaration and methods."""
        provider = test_domain.providers["default"]

        if provider.__class__.__name__ != "SqliteProvider":
            pytest.skip("Test specific to SqliteProvider")

        assert provider.capabilities == DatabaseCapabilities.RELATIONAL

        assert provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)
        assert provider.has_capability(DatabaseCapabilities.RAW_QUERIES)

        assert not provider.has_capability(DatabaseCapabilities.NATIVE_JSON)
        assert not provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY)
        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)

    def test_elasticsearch_provider_capabilities(self, test_domain):
        """Test ESProvider capability declaration and methods."""
        provider = test_domain.providers["default"]

        if provider.__class__.__name__ != "ESProvider":
            pytest.skip("Test specific to ESProvider")

        assert provider.capabilities == DatabaseCapabilities.DOCUMENT_STORE

        assert provider.has_capability(DatabaseCapabilities.CRUD)
        assert provider.has_capability(DatabaseCapabilities.SCHEMA_MANAGEMENT)
        assert provider.has_capability(DatabaseCapabilities.OPTIMISTIC_LOCKING)

        assert not provider.has_capability(DatabaseCapabilities.TRANSACTIONS)
        assert not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS)
        assert not provider.has_capability(DatabaseCapabilities.RAW_QUERIES)
        assert not provider.has_capability(DatabaseCapabilities.CONNECTION_POOLING)

    def test_has_all_capabilities(self, test_domain):
        """Test has_all_capabilities method with various combinations."""
        provider = test_domain.providers["default"]

        # Every provider should support BASIC_STORAGE
        assert provider.has_all_capabilities(DatabaseCapabilities.BASIC_STORAGE)
        assert provider.has_all_capabilities(DatabaseCapabilities.CRUD)
        assert provider.has_all_capabilities(
            DatabaseCapabilities.CRUD | DatabaseCapabilities.FILTER
        )

        # Empty capabilities should always return True
        assert provider.has_all_capabilities(DatabaseCapabilities(0))

        # Provider should have all its own capabilities
        assert provider.has_all_capabilities(provider.capabilities)

    def test_has_any_capability(self, test_domain):
        """Test has_any_capability method with various combinations."""
        provider = test_domain.providers["default"]

        # Should have any of the basic capabilities
        assert provider.has_any_capability(DatabaseCapabilities.CRUD)
        assert provider.has_any_capability(
            DatabaseCapabilities.CRUD | DatabaseCapabilities.NATIVE_JSON
        )

        # Empty capabilities should return False
        assert not provider.has_any_capability(DatabaseCapabilities(0))

    def test_has_any_capability_with_no_match(self, test_domain):
        """Test has_any_capability returns False when no capabilities match."""
        provider = test_domain.providers["default"]

        # Build a set of capabilities the provider does NOT have
        missing = DatabaseCapabilities(0)
        if not provider.has_capability(DatabaseCapabilities.TRANSACTIONS):
            missing |= DatabaseCapabilities.TRANSACTIONS
        if not provider.has_capability(DatabaseCapabilities.NATIVE_JSON):
            missing |= DatabaseCapabilities.NATIVE_JSON
        if not provider.has_capability(DatabaseCapabilities.NATIVE_ARRAY):
            missing |= DatabaseCapabilities.NATIVE_ARRAY
        if not provider.has_capability(DatabaseCapabilities.SIMULATED_TRANSACTIONS):
            missing |= DatabaseCapabilities.SIMULATED_TRANSACTIONS

        if missing:
            assert not provider.has_any_capability(missing)

    def test_has_all_capabilities_fails_for_superset(self, test_domain):
        """Test has_all_capabilities returns False for a superset of provider capabilities."""
        provider = test_domain.providers["default"]

        # All possible capabilities
        all_caps = (
            DatabaseCapabilities.RELATIONAL
            | DatabaseCapabilities.NATIVE_JSON
            | DatabaseCapabilities.NATIVE_ARRAY
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
        )

        # No single provider has all of these (TRANSACTIONS + SIMULATED_TRANSACTIONS
        # are mutually exclusive in the current adapter matrix)
        assert not provider.has_all_capabilities(all_caps)

    def test_combined_capability_checks(self, test_domain):
        """Test checking combinations of capabilities."""
        provider = test_domain.providers["default"]

        # Every provider should support basic storage
        assert provider.has_capability(DatabaseCapabilities.CRUD)
        assert provider.has_capability(DatabaseCapabilities.FILTER)
        assert provider.has_capability(DatabaseCapabilities.BULK_OPERATIONS)
        assert provider.has_capability(DatabaseCapabilities.ORDERING)

        assert provider.has_all_capabilities(DatabaseCapabilities.BASIC_STORAGE)

        # Every provider has either TRANSACTIONS or SIMULATED_TRANSACTIONS
        assert provider.has_any_capability(
            DatabaseCapabilities.TRANSACTIONS
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
        )
