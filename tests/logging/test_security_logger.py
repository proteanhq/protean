"""Tests for the dedicated ``protean.security`` logger.

Verifies that invariant violations, boundary-crossing validation failures,
and ``InvalidOperationError`` / ``InvalidStateError`` raises emit WARNING
events on the ``protean.security`` channel — while internal validation
failures caught by handler code do not.
"""

import logging

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import invariant
from protean.exceptions import (
    InvalidOperationError,
    InvalidStateError,
    ValidationError,
)
from protean.fields import Identifier, Integer
from protean.utils.mixins import handle


class Balance(BaseAggregate):
    account_id = Identifier(identifier=True)
    amount = Integer(default=0)

    @invariant.post
    def balance_non_negative(self):
        if self.amount < 0:
            raise ValidationError({"amount": ["Balance must be non-negative"]})


class Debit(BaseCommand):
    account_id = Identifier(identifier=True)
    amount = Integer()


class DebitHandler(BaseCommandHandler):
    @handle(Debit)
    def debit(self, command: Debit) -> None:
        from protean.utils.globals import current_domain

        repo = current_domain.repository_for(Balance)
        balance = Balance(account_id=command.account_id, amount=100)
        balance.amount = 100 - command.amount
        repo.add(balance)


class DebitWithInternalRetry(BaseCommand):
    account_id = Identifier(identifier=True)
    amount = Integer()


class DebitWithInternalRetryHandler(BaseCommandHandler):
    @handle(DebitWithInternalRetry)
    def debit(self, command: DebitWithInternalRetry) -> None:
        from protean.utils.globals import current_domain

        repo = current_domain.repository_for(Balance)
        balance = Balance(account_id=command.account_id, amount=100)
        # Deliberately try a failing update first, catch it, and retry with a
        # valid value. The caught ValidationError must NOT reach the boundary
        # and must NOT emit protean.security.validation_failed.
        try:
            balance.amount = -999
        except ValidationError:
            balance.amount = 50
        repo.add(balance)


class RaiseInvalidOperation(BaseCommand):
    account_id = Identifier(identifier=True)


class RaiseInvalidOperationHandler(BaseCommandHandler):
    @handle(RaiseInvalidOperation)
    def do_raise(self, command: RaiseInvalidOperation) -> None:
        raise InvalidOperationError("operation not allowed")


class RaiseInvalidState(BaseCommand):
    account_id = Identifier(identifier=True)


class RaiseInvalidStateHandler(BaseCommandHandler):
    @handle(RaiseInvalidState)
    def do_raise(self, command: RaiseInvalidState) -> None:
        raise InvalidStateError("state conflict")


class TestInvariantFailureLogged:
    """Aggregate invariant violations emit ``invariant_failed`` on ``protean.security``."""

    def test_invariant_failure_emits_warning_during_handler(self, test_domain, caplog):
        """Invariant violation that surfaces during command handling emits the event."""
        test_domain.register(Balance)
        test_domain.register(Debit, part_of=Balance)
        test_domain.register(DebitHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(ValidationError):
                test_domain.process(Debit(account_id="acc-1", amount=500))

        invariant_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invariant_failed"
        ]
        assert len(invariant_records) > 0, "Expected invariant_failed event"
        rec = invariant_records[0]
        assert rec.levelno == logging.WARNING
        assert getattr(rec, "aggregate", None) == "Balance"
        assert getattr(rec, "aggregate_id", None) == "acc-1"
        assert getattr(rec, "invariant", None)

    def test_invariant_failure_outside_handler_is_not_logged(self, test_domain, caplog):
        """Direct aggregate manipulation outside any handler stays off the channel."""
        test_domain.register(Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(ValidationError):
                balance = Balance(account_id="acc-1", amount=100)
                balance.amount = -50

        invariant_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invariant_failed"
        ]
        assert len(invariant_records) == 0, (
            "invariant_failed must not fire outside an active handler context"
        )

    def test_invariant_failure_includes_correlation(self, test_domain, caplog):
        test_domain.register(Balance)
        test_domain.register(Debit, part_of=Balance)
        test_domain.register(DebitHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(ValidationError):
                test_domain.process(Debit(account_id="acc-42", amount=500))

        invariant_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invariant_failed"
        ]
        assert len(invariant_records) > 0
        # correlation_id is populated by log_security_event — may be empty when
        # no domain message is yet in scope, but the attribute must exist.
        for rec in invariant_records:
            assert hasattr(rec, "correlation_id")


class TestValidationFailureAtBoundary:
    """Command handler failures that cross the boundary emit ``validation_failed``."""

    def test_validation_failure_at_domain_boundary(self, test_domain, caplog):
        test_domain.register(Balance)
        test_domain.register(Debit, part_of=Balance)
        test_domain.register(DebitHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(ValidationError):
                test_domain.process(Debit(account_id="acc-1", amount=500))

        boundary_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "validation_failed"
        ]
        assert len(boundary_records) > 0, "Expected validation_failed at boundary"
        rec = boundary_records[0]
        assert rec.levelno == logging.WARNING
        assert getattr(rec, "command_type", None)
        assert getattr(rec, "handler", None)

    def test_internal_validation_retries_not_logged_at_boundary(
        self, test_domain, caplog
    ):
        """Handlers that catch+retry ValidationError do not emit ``validation_failed``."""
        test_domain.register(Balance)
        test_domain.register(DebitWithInternalRetry, part_of=Balance)
        test_domain.register(DebitWithInternalRetryHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            test_domain.process(DebitWithInternalRetry(account_id="acc-2", amount=10))

        boundary_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "validation_failed"
        ]
        assert len(boundary_records) == 0, (
            "validation_failed must not fire when the handler caught the error"
        )


class TestInvalidOperationAndStateLogged:
    """``InvalidOperationError`` / ``InvalidStateError`` emit to ``protean.security``
    only when raised inside an active handler context — matching the gating
    applied to ``invariant_failed``.
    """

    def test_invalid_operation_inside_handler_logs_security_event(
        self, test_domain, caplog
    ):
        test_domain.register(Balance)
        test_domain.register(RaiseInvalidOperation, part_of=Balance)
        test_domain.register(RaiseInvalidOperationHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(InvalidOperationError):
                test_domain.process(RaiseInvalidOperation(account_id="acc-1"))

        records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invalid_operation"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert getattr(records[0], "detail", None) == "operation not allowed"

    def test_invalid_state_inside_handler_logs_security_event(
        self, test_domain, caplog
    ):
        test_domain.register(Balance)
        test_domain.register(RaiseInvalidState, part_of=Balance)
        test_domain.register(RaiseInvalidStateHandler, part_of=Balance)
        test_domain.init(traverse=False)

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(InvalidStateError):
                test_domain.process(RaiseInvalidState(account_id="acc-1"))

        records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invalid_state"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.WARNING
        assert getattr(records[0], "detail", None) == "state conflict"

    @pytest.mark.no_test_domain
    def test_invalid_operation_outside_handler_is_not_logged(self, caplog):
        """Raising outside any handler stays off the channel — fixtures, unit
        tests, REPL work, and framework internals that catch and recover
        (e.g., ``UnitOfWork`` state checks) do not pollute ``protean.security``.
        """
        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(InvalidOperationError):
                raise InvalidOperationError("operation not allowed")

        records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invalid_operation"
        ]
        assert len(records) == 0

    @pytest.mark.no_test_domain
    def test_invalid_state_outside_handler_is_not_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger="protean.security"):
            with pytest.raises(InvalidStateError):
                raise InvalidStateError("state conflict")

        records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "invalid_state"
        ]
        assert len(records) == 0


class TestSecurityLoggerRegistered:
    """The ``protean.security`` logger is registered at WARNING level."""

    def test_framework_logger_level(self):
        from protean.utils.logging import _FRAMEWORK_LOGGERS_NORMAL

        assert _FRAMEWORK_LOGGERS_NORMAL.get("protean.security") == logging.WARNING


class TestBoundaryEmitterHappyPath:
    """``_emit_validation_failed`` populates the expected fields."""

    @pytest.mark.no_test_domain
    def test_validation_error_at_boundary_is_logged(self, caplog):
        from protean.domain.command_processor import CommandProcessor

        with caplog.at_level(logging.WARNING, logger="protean.security"):
            CommandProcessor._emit_validation_failed(
                ValidationError({"x": ["bad"]}),
                command_type="my.domain.SomeCommand",
                handler_name="SomeHandler",
            )

        boundary_records = [
            r
            for r in caplog.records
            if r.name == "protean.security" and r.getMessage() == "validation_failed"
        ]
        assert len(boundary_records) == 1
        assert (
            getattr(boundary_records[0], "command_type", None)
            == "my.domain.SomeCommand"
        )
        assert getattr(boundary_records[0], "handler", None) == "SomeHandler"
