"""DomainFixture — test lifecycle manager for Protean domains."""

from collections.abc import Iterator
from contextlib import contextmanager

from protean.domain import Domain
from protean.domain.context import DomainContext, _domain_ctx_stack


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
            self.domain.setup_database()

    def teardown(self) -> None:
        """Drop database schema for every configured provider."""
        with self.domain.domain_context():
            self.domain.drop_database()

    @contextmanager
    def domain_context(self) -> Iterator[Domain]:
        """Per-test context manager: push domain, yield, reset stores, pop.

        Activates the domain context so ``current_domain`` resolves to this
        domain inside the test.  On exit, resets all data in this fixture's
        domain (its providers, brokers, and event store), then pops the
        context.  The context is popped even when a reset raises.

        A test that leaves another domain's context pushed still fails with
        ``AssertionError: Popped wrong domain context``.  Before that error
        is raised, the leaked contexts and this fixture's context are popped,
        so later tests start from the stack this fixture found.
        """
        ctx = self.domain.domain_context()
        ctx.push()

        try:
            yield self.domain
        finally:
            try:
                for provider in self.domain.providers.values():
                    provider._data_reset()

                for broker in self.domain.brokers.values():
                    broker._data_reset()

                self.domain._require_event_store()._data_reset()
            finally:
                try:
                    ctx.pop()
                except AssertionError:
                    _pop_through(ctx)
                    raise


def _pop_through(ctx: DomainContext) -> None:
    """Pop contexts off the stack down to and including ``ctx``.

    Leaves the stack unchanged when ``ctx`` is not on it.
    """
    popped: list[DomainContext] = []
    while (top := _domain_ctx_stack.pop()) is not None:
        if top is ctx:
            return
        popped.append(top)

    for other in reversed(popped):
        _domain_ctx_stack.push(other)
