import pytest

from protean.port.provider import BaseProvider, DatabaseCapabilities


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
        assert DatabaseCapabilities.NATIVE_CLAIM
        assert DatabaseCapabilities.BOUNDED_DELETE
        assert DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES

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
        """``in`` checks one flag or all of a set; ``&`` checks any of a set."""
        in_memory = DatabaseCapabilities.IN_MEMORY

        # has single capability
        assert DatabaseCapabilities.CRUD in in_memory
        assert DatabaseCapabilities.SIMULATED_TRANSACTIONS in in_memory
        assert DatabaseCapabilities.TRANSACTIONS not in in_memory

        # has all
        basic = DatabaseCapabilities.CRUD | DatabaseCapabilities.FILTER
        assert basic in in_memory

        # has any
        mixed = (
            DatabaseCapabilities.TRANSACTIONS
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
        )
        assert in_memory & mixed

        # does not have all of mixed
        assert mixed not in in_memory

    def test_claim_and_delete_flags_are_in_no_tier(self):
        """A provider opts into each claim and delete flag on its own."""
        claim_and_delete = (
            DatabaseCapabilities.NATIVE_CLAIM,
            DatabaseCapabilities.BOUNDED_DELETE,
            DatabaseCapabilities.FILTERED_CLAIM_CANDIDATES,
        )
        tiers = (
            DatabaseCapabilities.BASIC_STORAGE,
            DatabaseCapabilities.RELATIONAL,
            DatabaseCapabilities.DOCUMENT_STORE,
            DatabaseCapabilities.IN_MEMORY,
        )
        for flag in claim_and_delete:
            for tier in tiers:
                assert flag not in tier, f"{flag.name} is in {tier.name}"


def _declared_capabilities(provider_cls):
    # ``capabilities`` reads nothing from the instance, so skipping
    # ``__init__`` checks the declaration without a driver or a server.
    return object.__new__(provider_cls).capabilities


# Every single-bit member of ``DatabaseCapabilities``, listed flag by flag for
# each built-in provider class. A tier change or a new flag shows up here.
_YES, _NO = True, False
_DECLARED_CAPABILITIES: dict[str, dict[str, bool]] = {
    "MemoryProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _NO,
        "SIMULATED_TRANSACTIONS": _YES,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _NO,
        "CONNECTION_POOLING": _NO,
        "SCHEMA_MIGRATIONS": _NO,
        "NATIVE_JSON": _NO,
        "NATIVE_ARRAY": _NO,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _YES,
        "FILTERED_CLAIM_CANDIDATES": _NO,
    },
    "SAProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _YES,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _YES,
        "SCHEMA_MIGRATIONS": _YES,
        "NATIVE_JSON": _NO,
        "NATIVE_ARRAY": _NO,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _NO,
        "FILTERED_CLAIM_CANDIDATES": _NO,
    },
    "PostgresqlProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _YES,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _YES,
        "SCHEMA_MIGRATIONS": _YES,
        "NATIVE_JSON": _YES,
        "NATIVE_ARRAY": _YES,
        "NATIVE_CLAIM": _YES,
        "BOUNDED_DELETE": _YES,
        "FILTERED_CLAIM_CANDIDATES": _YES,
    },
    "SqliteProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _YES,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _YES,
        "SCHEMA_MIGRATIONS": _YES,
        "NATIVE_JSON": _NO,
        "NATIVE_ARRAY": _NO,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _YES,
        "FILTERED_CLAIM_CANDIDATES": _YES,
    },
    "MssqlProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _YES,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _YES,
        "SCHEMA_MIGRATIONS": _YES,
        "NATIVE_JSON": _YES,
        "NATIVE_ARRAY": _YES,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _YES,
        "FILTERED_CLAIM_CANDIDATES": _YES,
    },
    "MysqlProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _YES,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _YES,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _YES,
        "SCHEMA_MIGRATIONS": _YES,
        "NATIVE_JSON": _YES,
        "NATIVE_ARRAY": _NO,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _NO,
        "FILTERED_CLAIM_CANDIDATES": _YES,
    },
    "ESProvider": {
        "CRUD": _YES,
        "FILTER": _YES,
        "BULK_OPERATIONS": _YES,
        "ORDERING": _YES,
        "TRANSACTIONS": _NO,
        "SIMULATED_TRANSACTIONS": _NO,
        "OPTIMISTIC_LOCKING": _YES,
        "RAW_QUERIES": _NO,
        "SCHEMA_MANAGEMENT": _YES,
        "CONNECTION_POOLING": _NO,
        "SCHEMA_MIGRATIONS": _NO,
        "NATIVE_JSON": _NO,
        "NATIVE_ARRAY": _NO,
        "NATIVE_CLAIM": _NO,
        "BOUNDED_DELETE": _YES,
        "FILTERED_CLAIM_CANDIDATES": _NO,
    },
}


def _provider_class(class_name):
    if class_name == "MemoryProvider":
        from protean.adapters.repository.memory import MemoryProvider

        return MemoryProvider
    if class_name == "ESProvider":
        pytest.importorskip("elasticsearch", reason="Elasticsearch not available")
        from protean.adapters.repository.elasticsearch import ESProvider

        return ESProvider
    pytest.importorskip("sqlalchemy", reason="SQLAlchemy not available")
    from protean.adapters.repository import sqlalchemy

    if class_name == "SAProvider":
        # SAProvider is abstract, so read its declaration through a subclass
        # that adds only the dialect hooks and inherits ``capabilities``.
        class _InheritsSAProvider(sqlalchemy.SAProvider):
            def _get_database_specific_engine_args(self):
                return {}

            def _get_database_specific_session_args(self):
                return {}

            def _execute_database_specific_connection_statements(self, conn):
                return conn

        return _InheritsSAProvider
    return getattr(sqlalchemy, class_name)


def _expected_capabilities(class_name):
    expected = DatabaseCapabilities(0)
    for flag_name, declared in _DECLARED_CAPABILITIES[class_name].items():
        if declared:
            expected |= DatabaseCapabilities[flag_name]
    return expected


class TestProviderDeclaredCapabilities:
    """Each built-in provider class declares exactly the flags in the table."""

    @pytest.mark.parametrize("class_name", sorted(_DECLARED_CAPABILITIES))
    def test_provider_declares_exactly_its_row(self, class_name):
        capabilities = _declared_capabilities(_provider_class(class_name))

        assert capabilities == _expected_capabilities(class_name)

    @pytest.mark.parametrize("class_name", sorted(_DECLARED_CAPABILITIES))
    def test_row_names_every_flag(self, class_name):
        """Adding a flag to ``DatabaseCapabilities`` fails here until each
        provider's row says whether it declares the flag."""
        single_bit_flags = {flag.name for flag in DatabaseCapabilities}
        assert single_bit_flags, "DatabaseCapabilities has no members"

        assert set(_DECLARED_CAPABILITIES[class_name]) == single_bit_flags

    # The marker puts the test in every database leg, so it reads the live
    # provider of each service, not only memory.
    @pytest.mark.basic_storage
    def test_configured_provider_declares_its_row(self, test_domain):
        """The provider the test run configures returns its class's row."""
        provider = test_domain.providers["default"]
        class_name = provider.__class__.__name__
        assert class_name in _DECLARED_CAPABILITIES

        assert provider.capabilities == _expected_capabilities(class_name)


class TestProviderCapabilityChecks:
    """Check a configured provider's capabilities with ``in`` and ``&``."""

    def test_base_provider_has_no_capability_helpers(self):
        for name in ("has_capability", "has_all_capabilities", "has_any_capability"):
            assert not hasattr(BaseProvider, name), name

    def test_every_provider_has_basic_storage(self, test_domain):
        provider = test_domain.providers["default"]

        assert DatabaseCapabilities.BASIC_STORAGE in provider.capabilities

    def test_every_provider_has_real_or_simulated_transactions_but_not_both(
        self, test_domain
    ):
        provider = test_domain.providers["default"]
        either = (
            DatabaseCapabilities.TRANSACTIONS
            | DatabaseCapabilities.SIMULATED_TRANSACTIONS
        )

        # Elasticsearch declares neither, so the check only holds where
        # the provider has any transaction support at all.
        if provider.capabilities & either:
            assert either not in provider.capabilities


class TestRequiredLookups:
    """Test suite for REQUIRED_LOOKUPS constant and validate_lookups classmethod."""

    def test_required_lookups_is_frozenset(self):
        """REQUIRED_LOOKUPS should be an immutable frozenset."""
        assert isinstance(BaseProvider.REQUIRED_LOOKUPS, frozenset)

    def test_required_lookups_contains_expected_entries(self):
        """REQUIRED_LOOKUPS should contain all expected lookup names."""
        expected = {
            "exact",
            "iexact",
            "contains",
            "icontains",
            "startswith",
            "endswith",
            "gt",
            "gte",
            "lt",
            "lte",
            "in",
            "isnull",
        }
        assert expected == BaseProvider.REQUIRED_LOOKUPS

    def test_memory_provider_has_all_required_lookups(self):
        """MemoryProvider should register all required lookups."""
        from protean.adapters.repository.memory import MemoryProvider

        missing = MemoryProvider.validate_lookups()
        assert missing == [], f"MemoryProvider is missing lookups: {missing}"

    def test_sa_provider_has_all_required_lookups(self):
        """SAProvider should register all required lookups."""
        sa = pytest.importorskip("sqlalchemy", reason="SQLAlchemy not available")  # noqa: F841
        from protean.adapters.repository.sqlalchemy import SAProvider

        missing = SAProvider.validate_lookups()
        assert missing == [], f"SAProvider is missing lookups: {missing}"

    def test_es_provider_has_all_required_lookups(self):
        """ESProvider should register all required lookups."""
        pytest.importorskip("elasticsearch", reason="Elasticsearch not available")
        from protean.adapters.repository.elasticsearch import ESProvider

        missing = ESProvider.validate_lookups()
        assert missing == [], f"ESProvider is missing lookups: {missing}"

    def test_validate_lookups_returns_sorted_list(self):
        """validate_lookups should return a sorted list of missing lookup names."""
        from protean.port.dao import BaseLookup
        from protean.utils.query import RegisterLookupMixin

        # Create a minimal provider subclass with only a few lookups registered
        class PartialProvider(RegisterLookupMixin):
            REQUIRED_LOOKUPS = BaseProvider.REQUIRED_LOOKUPS

            @classmethod
            def validate_lookups(cls) -> list[str]:
                registered = set(cls.get_lookups().keys())
                return sorted(cls.REQUIRED_LOOKUPS - registered)

        @PartialProvider.register_lookup
        class ExactOnly(BaseLookup):
            lookup_name = "exact"

            def as_expression(self):
                return ""

        missing = PartialProvider.validate_lookups()
        assert missing == sorted(missing), "Missing lookups should be sorted"
        assert "exact" not in missing
        assert "contains" in missing

    def test_validate_lookups_returns_empty_when_all_present(self):
        """validate_lookups should return empty list when all lookups are registered."""
        from protean.adapters.repository.memory import MemoryProvider

        assert MemoryProvider.validate_lookups() == []

    def test_current_provider_passes_validation(self, test_domain):
        """The active test domain provider should have all required lookups."""
        provider = test_domain.providers["default"]
        missing = provider.__class__.validate_lookups()
        assert missing == [], (
            f"{provider.__class__.__name__} is missing required lookups: {missing}"
        )


class TestSchemaMigrationsCapability:
    """``SCHEMA_MIGRATIONS`` is left out of ``RELATIONAL`` and gates ``schema_migrator``."""

    def test_flag_is_not_part_of_relational(self):
        assert (
            DatabaseCapabilities.SCHEMA_MIGRATIONS
            not in DatabaseCapabilities.RELATIONAL
        )

    def test_schema_migrator_on_memory_provider_raises(self, tmp_path):
        from protean.adapters.repository.memory import MemoryProvider
        from protean.domain import Domain
        from protean.exceptions import NotSupportedError

        domain = Domain(name="Memory migrations")
        provider = MemoryProvider("default", domain, {"provider": "memory"})

        with pytest.raises(NotSupportedError, match="does not support schema"):
            provider.schema_migrator(tmp_path / "migrations")
        assert not (tmp_path / "migrations").exists()

    def test_base_method_raises_when_flag_is_declared_but_not_implemented(
        self, tmp_path
    ):
        """A provider that declares the flag and does not override
        ``_schema_migrator`` reaches the base method, which refuses."""
        from protean.adapters.repository.memory import MemoryProvider
        from protean.domain import Domain
        from protean.exceptions import NotSupportedError

        class DeclaresOnly(MemoryProvider):
            @property
            def capabilities(self):
                return (
                    DatabaseCapabilities.IN_MEMORY
                    | DatabaseCapabilities.SCHEMA_MIGRATIONS
                )

        domain = Domain(name="Declares only")
        provider = DeclaresOnly("default", domain, {"provider": "memory"})

        with pytest.raises(NotSupportedError, match="does not implement schema"):
            provider.schema_migrator(tmp_path / "migrations")
        assert not (tmp_path / "migrations").exists()
