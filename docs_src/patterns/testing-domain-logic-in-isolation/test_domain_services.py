# --8<-- [start:services]
import pytest
from isolation_shop.domain import Account, CreditPolicy, TransferService

from protean.exceptions import ValidationError


class TestTransferService:
    def test_valid_transfer(self):
        source = Account(balance=1000.0, risk_score=2)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        TransferService(source, policy).validate_and_debit(
            amount=500.0,
            transfer_id="txn-1",
            target_account_id="acc-2",
        )

        assert source.balance == 500.0

    def test_transfer_exceeding_policy_limit(self):
        source = Account(balance=10000.0, risk_score=2)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        with pytest.raises(ValidationError) as exc:
            TransferService(source, policy).validate_and_debit(
                amount=7000.0,
                transfer_id="txn-1",
                target_account_id="acc-2",
            )

        assert "Exceeds policy limit" in str(exc.value)
        assert source.balance == 10000.0  # Not debited

    def test_transfer_with_high_risk_score(self):
        source = Account(balance=1000.0, risk_score=8)
        policy = CreditPolicy(max_transfer_amount=5000.0, max_risk_score=5)

        with pytest.raises(ValidationError) as exc:
            TransferService(source, policy).validate_and_debit(
                amount=100.0,
                transfer_id="txn-1",
                target_account_id="acc-2",
            )

        assert "risk score exceeds" in str(exc.value)


# --8<-- [end:services]
