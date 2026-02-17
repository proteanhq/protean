"""DomainFixture — test lifecycle manager for Protean domains."""

from contextlib import contextmanager

from protean.domain import Domain


class DomainFixture:
    """Test lifecycle manager for a Protean domain.

    Handles domain initialization, database schema management,
    per-test context activation, and data store cleanup.

    Usage in conftest.py::

        import pytest
        from protean.integrations.pytest import DomainFixture

        @pytest.fixture(scope="session")
        def identity_fixture():
            from identity.domain import identity
            fixture = DomainFixture(identity)
            fixture.setup()
            yield fixture
            fixture.teardown()

        @pytest.fixture(autouse=True)
        def _ctx(identity_fixture):
            with identity_fixture.domain_context():
                yield
    """

    def __init__(self, domain: Domain) -> None:
        self.domain = domain

    def setup(self) -> None:
        """Initialize the domain and create database schema.

        Calls ``domain.init()`` to register all domain elements, then
        creates database tables for every configured provider.
        """
        self.domain.init()
        with self.domain.domain_context():
            for _, provider in self.domain.providers.items():
                provider._create_database_artifacts()

    def teardown(self) -> None:
        """Drop database schema for every configured provider."""
        with self.domain.domain_context():
            for _, provider in self.domain.providers.items():
                provider._drop_database_artifacts()

    @contextmanager
    def domain_context(self):
        """Per-test context manager: push domain, yield, reset stores, pop.

        Activates the domain context so ``current_domain`` resolves to this
        domain inside the test.  On exit, resets all data in providers,
        brokers, and the event store, then pops the context.
        """
        ctx = self.domain.domain_context()
        ctx.push()

        try:
            yield self.domain
        finally:
            from protean.utils.globals import current_domain

            for _, provider in current_domain.providers.items():
                provider._data_reset()

            for _, broker in current_domain.brokers.items():
                broker._data_reset()

            current_domain.event_store.store._data_reset()

            ctx.pop()
