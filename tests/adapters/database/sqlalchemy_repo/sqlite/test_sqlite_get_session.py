"""``SADatabase.get_session()`` returns the scoped session with a transaction
open, and a second call inside that transaction keeps it."""

import pytest

from tests.shared import provider_adapter


@pytest.fixture
def provider(test_domain):
    provider = provider_adapter(test_domain, "default")
    provider._scoped_session_cls.remove()
    yield provider
    provider._scoped_session_cls.remove()


@pytest.mark.sqlite
class TestSqliteGetSession:
    def test_get_session_opens_a_transaction(self, provider):
        assert provider._scoped_session_cls().in_transaction() is False

        session = provider.get_session()

        assert session.is_active is True
        assert session().in_transaction() is True

    def test_a_second_call_keeps_the_open_transaction(self, provider):
        first = provider.get_session()
        transaction = first().get_transaction()
        assert transaction is not None

        second = provider.get_session()

        assert second is first
        assert second().get_transaction() is transaction

    def test_get_connection_after_get_session_uses_the_same_transaction(self, provider):
        transaction = provider.get_session()().get_transaction()

        conn = provider.get_connection()

        assert conn.get_transaction() is transaction
