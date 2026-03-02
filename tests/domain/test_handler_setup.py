"""Tests for HandlerConfigurator — the extracted handler wiring logic.

These tests exercise the handler setup methods through the Domain's
``init()`` pipeline (the same way they run in production) to verify
that the extracted ``HandlerConfigurator`` class wires handlers correctly.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.query import BaseQuery
from protean.core.query_handler import BaseQueryHandler
from protean.exceptions import IncorrectUsageError, NotSupportedError
from protean.fields import Identifier, String
from protean.utils.mixins import handle, read


# ─── Shared fixtures ────────────────────────────────────────────────────


class Account(BaseAggregate):
    name: String(required=True)


class CreateAccount(BaseCommand):
    name: String(required=True)


class AccountCreated(BaseEvent):
    name: String(required=True)


# ─── Command Handler Setup ──────────────────────────────────────────────


class TestCommandHandlerSetup:
    """Verify that command handler methods are discovered and wired."""

    def test_command_handler_is_wired(self, test_domain):
        class AccountCommandHandler(BaseCommandHandler):
            @handle(CreateAccount)
            def create(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(AccountCommandHandler, part_of=Account)
        test_domain.init(traverse=False)

        assert len(AccountCommandHandler._handlers) == 1

    def test_duplicate_command_handler_raises_error(self, test_domain):
        class DuplicateHandler(BaseCommandHandler):
            @handle(CreateAccount)
            def create_one(self, command: CreateAccount) -> None:
                pass

            @handle(CreateAccount)
            def create_two(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(DuplicateHandler, part_of=Account)

        with pytest.raises(NotSupportedError, match="multiple handlers"):
            test_domain.init(traverse=False)

    def test_command_handler_targeting_non_command_raises_error(self, test_domain):
        class BadHandler(BaseCommandHandler):
            @handle(AccountCreated)  # Event, not Command
            def handle_event(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(BadHandler, part_of=Account)

        with pytest.raises(IncorrectUsageError, match="not associated with a command"):
            test_domain.init(traverse=False)

    def test_command_handler_aggregate_mismatch_raises_error(self, test_domain):
        class OtherAggregate(BaseAggregate):
            value: String()

        class MismatchedHandler(BaseCommandHandler):
            @handle(CreateAccount)
            def create(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(OtherAggregate)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(MismatchedHandler, part_of=OtherAggregate)

        with pytest.raises(
            IncorrectUsageError, match="not associated with the same aggregate"
        ):
            test_domain.init(traverse=False)


# ─── Event Handler Setup ────────────────────────────────────────────────


class TestEventHandlerSetup:
    """Verify that event handler methods are discovered and wired."""

    def test_event_handler_is_wired(self, test_domain):
        class AccountEventHandler(BaseEventHandler):
            @handle(AccountCreated)
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(AccountEventHandler, part_of=Account)
        test_domain.init(traverse=False)

        assert len(AccountEventHandler._handlers) == 1

    def test_any_wildcard_handler_is_wired(self, test_domain):
        class CatchAllHandler(BaseEventHandler):
            @handle("$any")
            def on_any(self, event) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CatchAllHandler, part_of=Account)
        test_domain.init(traverse=False)

        assert "$any" in CatchAllHandler._handlers


# ─── Projector Setup ────────────────────────────────────────────────────


class TestProjectorSetup:
    """Verify that projector handler methods are discovered and wired."""

    def test_projector_is_wired(self, test_domain):
        class AccountProjection(BaseProjection):
            name: String()
            account_id: Identifier(identifier=True)

        class AccountProjector(BaseProjector):
            @handle(AccountCreated)
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(AccountProjection)
        test_domain.register(
            AccountProjector,
            projector_for=AccountProjection,
            aggregates=[Account],
        )
        test_domain.init(traverse=False)

        assert len(AccountProjector._handlers) == 1

    def test_projector_targeting_non_event_raises_error(self, test_domain):
        class AccountProjection(BaseProjection):
            name: String()
            account_id: Identifier(identifier=True)

        class BadProjector(BaseProjector):
            @handle(CreateAccount)  # Command, not Event
            def on_command(self, command: CreateAccount) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(CreateAccount, part_of=Account)
        test_domain.register(AccountProjection)
        test_domain.register(
            BadProjector,
            projector_for=AccountProjection,
            aggregates=[Account],
        )

        with pytest.raises(IncorrectUsageError, match="not associated with an event"):
            test_domain.init(traverse=False)


# ─── Process Manager Setup ──────────────────────────────────────────────


class TestProcessManagerSetup:
    """Verify that process manager handler methods are discovered, validated,
    and wired, including transition event generation and stream inference."""

    def test_process_manager_missing_start_raises_error(self, test_domain):
        from protean.core.process_manager import BaseProcessManager

        class BadPM(BaseProcessManager):
            @handle(AccountCreated, correlate="name")
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(BadPM)

        with pytest.raises(IncorrectUsageError, match="start=True"):
            test_domain.init(traverse=False)

    def test_process_manager_missing_correlate_raises_error(self, test_domain):
        from protean.core.process_manager import BaseProcessManager

        class BadPM(BaseProcessManager):
            @handle(AccountCreated, start=True)
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(BadPM)

        with pytest.raises(IncorrectUsageError, match="correlate"):
            test_domain.init(traverse=False)

    def test_process_manager_generates_transition_event(self, test_domain):
        from protean.core.process_manager import BaseProcessManager

        class ValidPM(BaseProcessManager):
            @handle(AccountCreated, start=True, correlate="name")
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(ValidPM)
        test_domain.init(traverse=False)

        assert ValidPM._transition_event_cls is not None
        assert hasattr(ValidPM._transition_event_cls, "__type__")

    def test_process_manager_infers_stream_categories(self, test_domain):
        from protean.core.process_manager import BaseProcessManager

        class ValidPM(BaseProcessManager):
            @handle(AccountCreated, start=True, correlate="name")
            def on_created(self, event: AccountCreated) -> None:
                pass

        test_domain.register(Account)
        test_domain.register(AccountCreated, part_of=Account)
        test_domain.register(ValidPM)
        test_domain.init(traverse=False)

        assert len(ValidPM.meta_.stream_categories) > 0


# ─── Query Handler Setup ────────────────────────────────────────────────


class TestQueryHandlerSetup:
    """Verify that query handler methods are discovered and wired."""

    def test_query_handler_is_wired(self, test_domain):
        class AccountProjection(BaseProjection):
            name: String()
            account_id: Identifier(identifier=True)

        class GetAccount(BaseQuery):
            account_id: Identifier()

        class AccountQueryHandler(BaseQueryHandler):
            @read(GetAccount)
            def get_account(self, query: GetAccount):
                pass

        test_domain.register(AccountProjection)
        test_domain.register(GetAccount, part_of=AccountProjection)
        test_domain.register(AccountQueryHandler, part_of=AccountProjection)
        test_domain.init(traverse=False)

        assert len(AccountQueryHandler._handlers) == 1

    def test_query_handler_projection_mismatch_raises_error(self, test_domain):
        class Projection1(BaseProjection):
            name: String()
            p1_id: Identifier(identifier=True)

        class Projection2(BaseProjection):
            value: String()
            p2_id: Identifier(identifier=True)

        class GetFromP1(BaseQuery):
            some_id: Identifier()

        class BadQueryHandler(BaseQueryHandler):
            @read(GetFromP1)
            def get(self, query: GetFromP1):
                pass

        test_domain.register(Projection1)
        test_domain.register(Projection2)
        test_domain.register(GetFromP1, part_of=Projection1)
        test_domain.register(BadQueryHandler, part_of=Projection2)

        with pytest.raises(
            IncorrectUsageError, match="not associated with the same projection"
        ):
            test_domain.init(traverse=False)

    def test_duplicate_query_handler_raises_error(self, test_domain):
        class AccountProjection(BaseProjection):
            name: String()
            account_id: Identifier(identifier=True)

        class GetAccount(BaseQuery):
            account_id: Identifier()

        class DuplicateQueryHandler(BaseQueryHandler):
            @read(GetAccount)
            def get_one(self, query: GetAccount):
                pass

            @read(GetAccount)
            def get_two(self, query: GetAccount):
                pass

        test_domain.register(AccountProjection)
        test_domain.register(GetAccount, part_of=AccountProjection)
        test_domain.register(DuplicateQueryHandler, part_of=AccountProjection)

        with pytest.raises(NotSupportedError, match="multiple handlers"):
            test_domain.init(traverse=False)


# ─── Query Type Assignment ──────────────────────────────────────────────


class TestQueryTypeAssignment:
    """Verify that __type__ is set on query classes."""

    def test_query_type_is_set(self, test_domain):
        class AccountProjection(BaseProjection):
            name: String()
            account_id: Identifier(identifier=True)

        class FindAccount(BaseQuery):
            name: String()

        test_domain.register(AccountProjection)
        test_domain.register(FindAccount, part_of=AccountProjection)
        test_domain.init(traverse=False)

        assert hasattr(FindAccount, "__type__")
        assert "FindAccount" in FindAccount.__type__
