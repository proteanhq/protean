# --8<-- [start:post]
import pytest
from isolation_shop.domain import Account, Order

from protean.exceptions import ValidationError


class TestOrderInvariants:
    def test_order_must_have_items_when_placed(self):
        order = Order(customer_id="cust-123", total=50.0)
        # No items added -- invariant should fire

        with pytest.raises(ValidationError) as exc:
            # Trigger invariant check by modifying the aggregate
            order.status = "placed"

        assert "must have at least one item" in str(exc.value)
        assert order.status == "draft"  # The assignment is undone

    def test_discount_cannot_exceed_total(self):
        with pytest.raises(ValidationError) as exc:
            Order(
                customer_id="cust-123",
                total=50.0,
                discount=75.0,
            )
        assert "Discount cannot exceed" in str(exc.value)


class TestAccountInvariants:
    def test_balance_must_be_above_overdraft_limit(self):
        account = Account(balance=100.0, overdraft_limit=50.0)

        # This should fail the invariant
        with pytest.raises(ValidationError) as exc:
            account.balance = -100.0  # Below -50 overdraft limit

        assert "below overdraft limit" in str(exc.value)
        assert account.balance == 100.0


# --8<-- [end:post]


# --8<-- [start:pre]
class TestAccountPreInvariants:
    def test_closed_account_cannot_change(self):
        account = Account(balance=100.0, status="closed")

        with pytest.raises(ValidationError) as exc:
            account.balance = 50.0

        assert "Closed accounts cannot be changed" in str(exc.value)
        assert account.balance == 100.0


# --8<-- [end:pre]
