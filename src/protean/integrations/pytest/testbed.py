"""DomainFixture — test lifecycle manager for Protean domains."""

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from protean.domain import Domain
from protean.domain.context import DomainContext, _domain_ctx_stack
from protean.port.broker import BaseBroker


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
        """Initialize the domain, create database schema, and check brokers.

        Calls ``domain.init()`` to register all domain elements, then
        creates database tables for every configured provider.

        Finally pings every configured broker once and emits a
        ``UserWarning`` for each one that does not answer. The warning names
        the broker and its URI, with any password replaced by ``***``.
        ``setup()`` still returns normally, so tests that never touch the
        broker keep running.
        Run pytest with ``-W error::UserWarning`` to make the warning fatal.
        """
        self.domain.init()
        with self.domain.domain_context():
            self.domain.setup_database()

            for name, broker in self.domain.brokers.items():
                if not broker.ping():
                    warnings.warn(
                        f"{_describe_broker(name, broker)} is unreachable. "
                        "Tests that publish to it will fail, and the per-test "
                        "reset cannot clear it.",
                        UserWarning,
                        stacklevel=2,
                    )

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


def _describe_broker(name: str, broker: BaseBroker) -> str:
    """Name a broker for a warning, showing its URI without the password."""
    uri = broker.conn_info.get("URI")
    display = _display_uri(uri) if uri is not None else None
    if display is not None:
        return f"Broker '{name}' at {display}"

    return f"Broker '{name}' ({broker.conn_info.get('provider')} provider)"


def _display_uri(uri: object) -> str | None:
    """Return ``uri`` with any password replaced by ``***``.

    Returns ``None`` when ``uri`` is not a string or cannot be parsed, so the
    caller never falls back to showing the raw value.
    """
    if not isinstance(uri, str):
        return None

    try:
        parts = urlsplit(uri)
        # ``port`` is parsed lazily; reading it rejects a malformed netloc.
        _ = parts.port
    except ValueError:
        return None

    if not parts.hostname:
        return None

    userinfo, at, hostport = parts.netloc.rpartition("@")
    if at:
        username, colon, _ = userinfo.partition(":")
        netloc = f"{username}{':***' if colon else ''}@{hostport}"
    else:
        netloc = hostport

    # redis-py also accepts the password as a query argument.
    query = urlencode(
        [
            (key, "***" if key.lower() == "password" else value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
        ],
        safe="*",
    )

    # The fragment is dropped: an unencoded ``#`` in a password lands there.
    return urlunsplit((parts.scheme, netloc, parts.path, query, ""))
