"""Reflect a DB-assigned ``Auto(increment=True)`` value back onto the aggregate.

``repository.add()`` must populate an ``Auto(increment=True)`` identifier on the
*same* instance the caller passed in — not just onto a re-fetched copy — under
both a standalone add and an add nested in an outer ``UnitOfWork``.

For the in-memory provider the value is assigned during ``_create`` and reflected
directly. For relational adapters (SQLAlchemy → Postgres/SQLite/MSSQL) the value
is a DB-assigned autoincrement primary key that only materializes on flush; under
an outer UoW that flush is otherwise deferred to commit, after ``add()`` returns.
``save()``/``create()`` therefore force a flush before reflecting when an
auto-increment field is still pending. These ``@pytest.mark.transactional`` tests
run on every provider with (real or simulated) transaction support, so they guard
the behaviour across both worlds.

The relational fail-without-fix teeth are on SQLite/Postgres/MSSQL; on the memory
leg the value is assigned during ``_create`` regardless, so the memory run is a
no-regression guard rather than a falsification of the fix.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.unit_of_work import UnitOfWork
from protean.fields import Auto, String


class Ticket(BaseAggregate):
    ticket_no = Auto(increment=True, identifier=True)
    subject = String(required=True)


class AliasTicket(BaseAggregate):
    """Auto-increment identifier stored under a different column name."""

    ticket_no = Auto(increment=True, identifier=True, referenced_as="tno")
    subject = String(required=True)


class Memo(BaseAggregate):
    """No auto-increment field: the default identifier is a client-side UUID."""

    body = String(required=True)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Ticket)
    test_domain.register(AliasTicket)
    test_domain.register(Memo)
    test_domain.init(traverse=False)


@pytest.mark.transactional
class TestAutoIncrementReflection:
    def test_standalone_add_reflects_identifier_onto_original_instance(
        self, test_domain
    ):
        """A standalone ``add()`` populates the auto-increment identifier on the
        instance the caller holds, so it can be referenced afterwards."""
        ticket = Ticket(subject="standalone")
        assert ticket.ticket_no is None  # not generated until persisted

        test_domain.repository_for(Ticket).add(ticket)

        assert ticket.ticket_no is not None
        # The reflected id resolves the persisted record.
        assert test_domain.repository_for(Ticket).get(ticket.ticket_no).subject == (
            "standalone"
        )

    def test_add_within_unit_of_work_reflects_identifier_onto_original_instance(
        self, test_domain
    ):
        """An ``add()`` inside an outer ``UnitOfWork`` also reflects the value —
        the relational path where the flush would otherwise land only at commit,
        after ``add()`` has returned."""
        ticket = Ticket(subject="in-uow")
        assert ticket.ticket_no is None

        with UnitOfWork():
            test_domain.repository_for(Ticket).add(ticket)

        assert ticket.ticket_no is not None
        assert test_domain.repository_for(Ticket).get(ticket.ticket_no).subject == (
            "in-uow"
        )

    def test_reflected_identifiers_are_monotonic(self, test_domain):
        """Successive adds reflect distinct, increasing values — and each reflected
        value actually resolves its own persisted record, confirming the value is
        the real store-generated key rather than an in-memory constant/counter."""
        repo = test_domain.repository_for(Ticket)

        first = Ticket(subject="first")
        repo.add(first)

        second = Ticket(subject="second")
        with UnitOfWork():
            repo.add(second)

        assert first.ticket_no is not None
        assert second.ticket_no is not None
        assert second.ticket_no > first.ticket_no
        # Each reflected id ties back to the record it persisted.
        assert repo.get(first.ticket_no).subject == "first"
        assert repo.get(second.ticket_no).subject == "second"

    def test_dao_create_within_unit_of_work_reflects_identifier(self, test_domain):
        """``dao.create()`` is the sibling create path (not routed through
        ``save()``); it must reflect the value under a UoW too — the flush is
        otherwise deferred to commit."""
        dao = test_domain.repository_for(Ticket)._dao

        with UnitOfWork():
            created = dao.create(subject="via create in uow")

        assert created.ticket_no is not None
        assert test_domain.repository_for(Ticket).get(created.ticket_no).subject == (
            "via create in uow"
        )

    def test_standalone_dao_save_reflects_identifier(self, test_domain):
        """A direct ``dao.save()`` with no active ``UnitOfWork`` reflects the
        value via the standalone commit path (no forced flush needed)."""
        ticket = Ticket(subject="standalone dao.save")
        assert ticket.ticket_no is None

        test_domain.repository_for(Ticket)._dao.save(ticket)

        assert ticket.ticket_no is not None
        assert test_domain.repository_for(Ticket).get(ticket.ticket_no).subject == (
            "standalone dao.save"
        )

    def test_standalone_dao_create_reflects_identifier(self, test_domain):
        """The standalone counterpart of ``dao.create()`` (no UoW) reflects via
        the commit path, mirroring the standalone ``save()`` coverage."""
        created = test_domain.repository_for(Ticket)._dao.create(
            subject="standalone create"
        )

        assert created.ticket_no is not None
        assert test_domain.repository_for(Ticket).get(created.ticket_no).subject == (
            "standalone create"
        )

    def test_referenced_as_identifier_reflected(self, test_domain):
        """An auto-increment identifier stored under a ``referenced_as`` column
        is read back off the model by its attribute name, not the field name.
        Without that, reflection raises ``AttributeError`` on SQLAlchemy."""
        ticket = AliasTicket(subject="aliased")
        assert ticket.ticket_no is None

        with UnitOfWork():
            test_domain.repository_for(AliasTicket).add(ticket)

        assert ticket.ticket_no is not None

    def test_caller_supplied_auto_value_is_not_overwritten(self, test_domain):
        """A caller-supplied value on an ``Auto(increment=True)`` identifier is
        left untouched — reflection only fills fields still unset."""
        ticket = Ticket(ticket_no=4242, subject="preset")
        assert ticket.ticket_no == 4242

        with UnitOfWork():
            test_domain.repository_for(Ticket).add(ticket)

        assert ticket.ticket_no == 4242
        assert test_domain.repository_for(Ticket).get(4242).subject == "preset"

    def test_no_flush_forced_without_a_pending_auto_field(
        self, test_domain, monkeypatch
    ):
        """An aggregate with a client-supplied identifier (no pending auto field)
        must not pay a forced flush under a UoW — the guard exists precisely so the
        common non-auto path is untouched."""
        dao = test_domain.repository_for(Memo)._dao
        flush_calls = {"count": 0}
        original_flush = type(dao)._flush

        def counting_flush(self):
            flush_calls["count"] += 1
            return original_flush(self)

        monkeypatch.setattr(type(dao), "_flush", counting_flush)

        with UnitOfWork():
            test_domain.repository_for(Memo).add(Memo(body="no auto here"))

        assert flush_calls["count"] == 0
