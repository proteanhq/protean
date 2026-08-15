"""A failed domain-service invariant carries a coded diagnostic.

Domain services run their invariants through a separate wrapper from the entity
and value-object runners, so this covers that path: the default per-stage codes,
the `@invariant.pre/post(code=...)` override, and the location.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.domain_service import BaseDomainService
from protean.core.entity import invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier
from protean.ir.diagnostics import DiagnosticCode, resolve

PRE = DiagnosticCode.INVARIANT_PRE_FAILED.value
POST = DiagnosticCode.INVARIANT_POST_FAILED.value


class Account(BaseAggregate):
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)


class Ledger(BaseAggregate):
    ledger_id: Identifier(identifier=True)
    total: Float(default=0.0)


class RecordTransfer(BaseDomainService):
    def __init__(self, account, ledger, amount):
        super().__init__(account, ledger)
        self.account = account
        self.ledger = ledger
        self.amount = amount

    @invariant.pre
    def amount_within_balance(self):
        if self.amount > self.account.balance:
            raise ValidationError({"_service": ["Insufficient funds"]})

    @invariant.pre(code="TRANSFER_NON_POSITIVE")
    def amount_is_positive(self):
        if self.amount <= 0:
            raise ValidationError({"_service": ["Amount must be positive"]})

    @invariant.post
    def ledger_within_cap(self):
        if self.ledger.total > 1000:
            raise ValidationError({"_service": ["Ledger over cap"]})

    def __call__(self):
        self.account.balance -= self.amount
        self.ledger.total += self.amount


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(Ledger)
    test_domain.register(RecordTransfer, part_of=[Account, Ledger])
    test_domain.init(traverse=False)


def _account(balance):
    return Account(account_id="a", balance=balance)


def _ledger(total=0.0):
    return Ledger(ledger_id="l", total=total)


class TestDomainServiceInvariantCodes:
    def test_pre_invariant_failure_carries_the_pre_code(self):
        with pytest.raises(ValidationError) as exc:
            RecordTransfer(_account(100.0), _ledger(), 200.0)()

        assert exc.value.code == PRE
        assert exc.value.codes == [PRE]
        assert exc.value.location == "RecordTransfer"

    def test_custom_pre_code_is_carried(self):
        with pytest.raises(ValidationError) as exc:
            RecordTransfer(_account(100.0), _ledger(), -5.0)()

        assert exc.value.code == "TRANSFER_NON_POSITIVE"
        assert exc.value.codes == ["TRANSFER_NON_POSITIVE"]

    def test_post_invariant_failure_carries_the_post_code(self):
        with pytest.raises(ValidationError) as exc:
            RecordTransfer(_account(5000.0), _ledger(), 2000.0)()

        assert exc.value.code == POST
        assert exc.value.codes == [POST]
        assert exc.value.location == "RecordTransfer"

    def test_rationale_and_fix_resolve_from_the_registry(self):
        with pytest.raises(ValidationError) as exc:
            RecordTransfer(_account(100.0), _ledger(), 200.0)()

        meta = resolve(DiagnosticCode.INVARIANT_PRE_FAILED)
        assert exc.value.rationale == meta.rationale
        assert exc.value.fix == meta.fix

    def test_a_valid_transfer_runs_without_a_coded_error(self):
        account, ledger = _account(5000.0), _ledger()
        RecordTransfer(account, ledger, 500.0)()
        assert account.balance == 4500.0
        assert ledger.total == 500.0
