"""A Unit of Work commits a shared store's ``default`` session before the
session of another provider, even when the other provider enlisted first.

A crash between the two commits then leaves events with no aggregate row,
which reconciliation recovers, and never an aggregate row with no events.
"""

from collections.abc import Callable
from typing import Any

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate, apply
from protean.core.event import BaseEvent
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ObjectNotFoundError, TransactionError
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

from .conftest import BACKENDS, row_count


class Opened(BaseEvent):
    account_id = Identifier(required=True)


class Account(BaseAggregate):
    name = String()

    @apply
    def on_opened(self, event: Opened) -> None:
        self.id = event.account_id


class Invoice(BaseAggregate):
    number = String()


def register(domain: Domain) -> None:
    domain.register(Account, event_sourced=True)
    domain.register(Opened, part_of=Account)
    domain.register(Invoice, database="secondary")


SECONDARY = {"secondary": {"provider": "memory"}}


@pytest.fixture
def commits(monkeypatch) -> Callable[[str | None], list[str]]:
    """Record the provider of each session commit, and fail one provider's."""

    def trace(failing: str | None = None) -> list[str]:
        recorded: list[str] = []
        initialize = UnitOfWork._initialize_session

        def traced(self: UnitOfWork, provider_name: str, domain: Any = None) -> Any:
            session = initialize(self, provider_name, domain)
            commit = session.commit

            def traced_commit() -> None:
                recorded.append(provider_name)
                if provider_name == failing:
                    raise RuntimeError(f"the {provider_name} commit fails")
                commit()

            session.commit = traced_commit  # type: ignore[method-assign]
            return session

        monkeypatch.setattr(UnitOfWork, "_initialize_session", traced)
        return recorded

    return trace


def save_invoice_then_account() -> str:
    """Save an invoice on ``secondary``, then an event-sourced account on
    the shared store, in one Unit of Work. Returns the invoice's id."""
    with UnitOfWork():
        invoice = Invoice(number="1")
        current_domain.repository_for(Invoice).add(invoice)
        account = Account(id="a1")
        account.raise_(Opened(account_id="a1"))
        current_domain.repository_for(Account).add(account)
    return str(invoice.id)


def invoice_exists(invoice_id: str) -> bool:
    try:
        current_domain.repository_for(Invoice).get(invoice_id)
    except ObjectNotFoundError:
        return False
    return True


@pytest.mark.no_test_domain
@pytest.mark.parametrize("backend", BACKENDS)
class TestDefaultCommitsFirst:
    def test_default_commits_before_a_provider_that_enlisted_first(
        self, make_shared_domain, commits
    ):
        domain = make_shared_domain(register, databases=SECONDARY)
        recorded = commits()

        invoice_id = save_invoice_then_account()

        assert recorded == ["default", "secondary"]
        assert row_count(domain, "messages") == 1
        assert invoice_exists(invoice_id)

    def test_a_failed_default_commit_stores_nothing(self, make_shared_domain, commits):
        domain = make_shared_domain(register, databases=SECONDARY)
        recorded = commits("default")

        with pytest.raises(TransactionError, match="the default commit fails"):
            save_invoice_then_account()

        assert recorded == ["default"]
        assert row_count(domain, "messages") == 0
        assert current_domain.repository_for(Invoice)._dao.query.all().total == 0

    def test_a_failed_later_commit_keeps_the_events(self, make_shared_domain, commits):
        domain = make_shared_domain(register, databases=SECONDARY)
        recorded = commits("secondary")

        with pytest.raises(TransactionError, match="the secondary commit fails"):
            save_invoice_then_account()

        assert recorded == ["default", "secondary"]
        assert row_count(domain, "messages") == 1
        assert current_domain.repository_for(Invoice)._dao.query.all().total == 0
