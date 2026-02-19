"""Advanced tests for the ``given`` DSL.

Covers event handler processing during seeding, aggregates with
ValueObject/HasMany fields, and edge cases.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, Integer, String, ValueObject
from protean.testing import given
from protean.utils.globals import current_domain
from protean.utils.mixins import handle


# ===========================================================================
# Scenario 1: Event handler fires during seeding
# ===========================================================================
class AccountOpened(BaseEvent):
    account_id = Identifier(required=True)
    holder = String(required=True)
    balance = Float(required=True)


class DepositMade(BaseEvent):
    account_id = Identifier(required=True)
    amount = Float(required=True)


class WithdrawalMade(BaseEvent):
    account_id = Identifier(required=True)
    amount = Float(required=True)


class OpenAccount(BaseCommand):
    account_id = Identifier(identifier=True)
    holder = String(required=True)
    initial_balance = Float(required=True)


class MakeDeposit(BaseCommand):
    account_id = Identifier(identifier=True)
    amount = Float(required=True)


class MakeWithdrawal(BaseCommand):
    account_id = Identifier(identifier=True)
    amount = Float(required=True)


class Account(BaseAggregate):
    account_id = Identifier(identifier=True)
    holder = String(required=True)
    balance = Float(default=0.0)

    @classmethod
    def open(cls, account_id: str, holder: str, initial_balance: float) -> "Account":
        account = cls._create_new(account_id=account_id)
        account.raise_(
            AccountOpened(
                account_id=account_id,
                holder=holder,
                balance=initial_balance,
            )
        )
        return account

    def deposit(self, amount: float) -> None:
        self.raise_(DepositMade(account_id=self.account_id, amount=amount))

    def withdraw(self, amount: float) -> None:
        if amount > (self.balance or 0.0):
            raise ValidationError({"account": ["Insufficient funds"]})
        self.raise_(WithdrawalMade(account_id=self.account_id, amount=amount))

    @apply
    def on_opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.holder = event.holder
        self.balance = event.balance

    @apply
    def on_deposit(self, event: DepositMade) -> None:
        self.balance = (self.balance or 0.0) + event.amount

    @apply
    def on_withdrawal(self, event: WithdrawalMade) -> None:
        self.balance = (self.balance or 0.0) - event.amount


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def handle_open(self, command: OpenAccount) -> None:
        account = Account.open(
            command.account_id, command.holder, command.initial_balance
        )
        current_domain.repository_for(Account).add(account)

    @handle(MakeDeposit)
    def handle_deposit(self, command: MakeDeposit) -> None:
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount)
        repo.add(account)

    @handle(MakeWithdrawal)
    def handle_withdrawal(self, command: MakeWithdrawal) -> None:
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount)
        repo.add(account)


# Transaction counter - tracks how many events the event handler has seen
transaction_counter: dict[str, int] = {}


class AccountEventHandler(BaseEventHandler):
    @handle(AccountOpened)
    def on_opened(self, event: AccountOpened) -> None:
        transaction_counter[event.account_id] = 1

    @handle(DepositMade)
    def on_deposit(self, event: DepositMade) -> None:
        transaction_counter.setdefault(event.account_id, 0)
        transaction_counter[event.account_id] += 1


# ===========================================================================
# Scenario 2: Aggregate with ValueObject
# ===========================================================================
class Money(BaseValueObject):
    amount = Float(required=True)
    currency = String(default="USD")


class InvoiceCreated(BaseEvent):
    invoice_id = Identifier(required=True)
    total_amount = Float(required=True)
    total_currency = String(default="USD")


class InvoicePaid(BaseEvent):
    invoice_id = Identifier(required=True)


class CreateInvoice(BaseCommand):
    invoice_id = Identifier(identifier=True)
    total_amount = Float(required=True)
    total_currency = String(default="USD")


class PayInvoice(BaseCommand):
    invoice_id = Identifier(identifier=True)


class Invoice(BaseAggregate):
    invoice_id = Identifier(identifier=True)
    total = ValueObject(Money)
    paid = String(default="NO")

    @classmethod
    def create(
        cls, invoice_id: str, total_amount: float, total_currency: str = "USD"
    ) -> "Invoice":
        inv = cls._create_new(invoice_id=invoice_id)
        inv.raise_(
            InvoiceCreated(
                invoice_id=invoice_id,
                total_amount=total_amount,
                total_currency=total_currency,
            )
        )
        return inv

    def pay(self) -> None:
        if self.paid == "YES":
            raise ValidationError({"invoice": ["Already paid"]})
        self.raise_(InvoicePaid(invoice_id=self.invoice_id))

    @apply
    def on_created(self, event: InvoiceCreated) -> None:
        self.invoice_id = event.invoice_id
        self.total = Money(amount=event.total_amount, currency=event.total_currency)
        self.paid = "NO"

    @apply
    def on_paid(self, event: InvoicePaid) -> None:
        self.paid = "YES"


class InvoiceCommandHandler(BaseCommandHandler):
    @handle(CreateInvoice)
    def handle_create(self, command: CreateInvoice) -> str:
        inv = Invoice.create(
            command.invoice_id, command.total_amount, command.total_currency
        )
        current_domain.repository_for(Invoice).add(inv)
        return inv.invoice_id

    @handle(PayInvoice)
    def handle_pay(self, command: PayInvoice) -> None:
        repo = current_domain.repository_for(Invoice)
        inv = repo.get(command.invoice_id)
        inv.pay()
        repo.add(inv)


# ===========================================================================
# Scenario 3: Aggregate with HasMany
# ===========================================================================
class CartItem(BaseEntity):
    product = String(required=True)
    qty = Integer(default=1)


class CartCreated(BaseEvent):
    cart_id = Identifier(required=True)
    owner = String(required=True)


class ItemAddedToCart(BaseEvent):
    cart_id = Identifier(required=True)
    product = String(required=True)
    qty = Integer(required=True)


class CheckoutCart(BaseCommand):
    cart_id = Identifier(identifier=True)


class AddItemToCart(BaseCommand):
    cart_id = Identifier(identifier=True)
    product = String(required=True)
    qty = Integer(required=True)


class CartCheckedOut(BaseEvent):
    cart_id = Identifier(required=True)


class Cart(BaseAggregate):
    cart_id = Identifier(identifier=True)
    owner = String(required=True)
    items = HasMany(CartItem)
    checked_out = String(default="NO")

    @classmethod
    def create(cls, cart_id: str, owner: str) -> "Cart":
        cart = cls._create_new(cart_id=cart_id)
        cart.raise_(CartCreated(cart_id=cart_id, owner=owner))
        return cart

    def add_item(self, product: str, qty: int) -> None:
        self.raise_(ItemAddedToCart(cart_id=self.cart_id, product=product, qty=qty))

    def checkout(self) -> None:
        if not self.items or len(self.items) == 0:
            raise ValidationError({"cart": ["Cannot checkout empty cart"]})
        self.raise_(CartCheckedOut(cart_id=self.cart_id))

    @apply
    def on_created(self, event: CartCreated) -> None:
        self.cart_id = event.cart_id
        self.owner = event.owner

    @apply
    def on_item_added(self, event: ItemAddedToCart) -> None:
        self.add_items(CartItem(product=event.product, qty=event.qty))

    @apply
    def on_checked_out(self, event: CartCheckedOut) -> None:
        self.checked_out = "YES"


class CartCommandHandler(BaseCommandHandler):
    @handle(AddItemToCart)
    def handle_add_item(self, command: AddItemToCart) -> None:
        repo = current_domain.repository_for(Cart)
        cart = repo.get(command.cart_id)
        cart.add_item(command.product, command.qty)
        repo.add(cart)

    @handle(CheckoutCart)
    def handle_checkout(self, command: CheckoutCart) -> None:
        repo = current_domain.repository_for(Cart)
        cart = repo.get(command.cart_id)
        cart.checkout()
        repo.add(cart)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def register_elements(test_domain):
    # Account
    test_domain.register(Account, is_event_sourced=True)
    test_domain.register(AccountOpened, part_of=Account)
    test_domain.register(DepositMade, part_of=Account)
    test_domain.register(WithdrawalMade, part_of=Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(MakeDeposit, part_of=Account)
    test_domain.register(MakeWithdrawal, part_of=Account)
    test_domain.register(AccountCommandHandler, part_of=Account)
    test_domain.register(AccountEventHandler, part_of=Account)

    # Invoice
    test_domain.register(Invoice, is_event_sourced=True)
    test_domain.register(InvoiceCreated, part_of=Invoice)
    test_domain.register(InvoicePaid, part_of=Invoice)
    test_domain.register(CreateInvoice, part_of=Invoice)
    test_domain.register(PayInvoice, part_of=Invoice)
    test_domain.register(InvoiceCommandHandler, part_of=Invoice)

    # Cart
    test_domain.register(Cart, is_event_sourced=True)
    test_domain.register(CartItem, part_of=Cart)
    test_domain.register(CartCreated, part_of=Cart)
    test_domain.register(ItemAddedToCart, part_of=Cart)
    test_domain.register(CartCheckedOut, part_of=Cart)
    test_domain.register(AddItemToCart, part_of=Cart)
    test_domain.register(CheckoutCart, part_of=Cart)
    test_domain.register(CartCommandHandler, part_of=Cart)

    test_domain.init(traverse=False)


@pytest.fixture(autouse=True)
def clear_counter():
    transaction_counter.clear()
    yield
    transaction_counter.clear()


# ---------------------------------------------------------------------------
# Tests: Event handler processing during seed
# ---------------------------------------------------------------------------
class TestEventHandlerDuringSeed:
    @pytest.mark.eventstore
    def test_event_handlers_fire_for_seeded_events(self):
        """Event handlers process seeded events (sync mode),
        matching what UoW commit does."""
        aid = str(uuid4())
        opened = AccountOpened(account_id=aid, holder="Alice", balance=100.0)
        deposit = DepositMade(account_id=aid, amount=50.0)

        result = given(Account, opened, deposit).process(
            MakeWithdrawal(account_id=aid, amount=30.0)
        )

        assert result.accepted
        # Event handler should have incremented counter:
        # 1 for opened + 1 for deposit = 2
        assert transaction_counter.get(aid) == 2

    @pytest.mark.eventstore
    def test_event_handlers_skipped_when_not_sync(self, test_domain):
        """When event_processing is not 'sync', seeded events
        do NOT trigger event handlers."""
        original = test_domain.config["event_processing"]
        test_domain.config["event_processing"] = "async"
        try:
            aid = str(uuid4())
            opened = AccountOpened(account_id=aid, holder="Bob", balance=200.0)

            result = given(Account, opened).process(
                MakeDeposit(account_id=aid, amount=10.0)
            )

            assert result.accepted
            # Event handler should NOT have been called
            assert transaction_counter.get(aid) is None
        finally:
            test_domain.config["event_processing"] = original


# ---------------------------------------------------------------------------
# Tests: Aggregates with ValueObject fields
# ---------------------------------------------------------------------------
class TestValueObjectAggregates:
    @pytest.mark.eventstore
    def test_given_seeds_aggregate_with_value_object(self):
        """given() correctly seeds events for aggregates with VO fields."""
        iid = str(uuid4())
        created = InvoiceCreated(
            invoice_id=iid, total_amount=250.0, total_currency="EUR"
        )

        result = given(Invoice, created).process(PayInvoice(invoice_id=iid))

        assert result.accepted
        assert result.paid == "YES"
        assert result.total.amount == 250.0
        assert result.total.currency == "EUR"

    @pytest.mark.eventstore
    def test_create_command_with_value_object(self):
        """Create command for aggregate with VO fields works."""
        iid = str(uuid4())
        result = given(Invoice).process(
            CreateInvoice(invoice_id=iid, total_amount=100.0, total_currency="USD")
        )

        assert result.accepted
        assert result.total.amount == 100.0
        assert result.total.currency == "USD"
        assert result.paid == "NO"


# ---------------------------------------------------------------------------
# Tests: Aggregates with HasMany fields
# ---------------------------------------------------------------------------
class TestHasManyAggregates:
    @pytest.mark.eventstore
    def test_given_seeds_aggregate_with_has_many(self):
        """given() correctly seeds events that add child entities."""
        cid = str(uuid4())
        created = CartCreated(cart_id=cid, owner="Bob")
        item1 = ItemAddedToCart(cart_id=cid, product="Widget", qty=2)
        item2 = ItemAddedToCart(cart_id=cid, product="Gadget", qty=1)

        result = given(Cart, created, item1, item2).process(CheckoutCart(cart_id=cid))

        assert result.accepted
        assert result.checked_out == "YES"
        assert len(result.items) == 2
        assert CartCheckedOut in result.events

    @pytest.mark.eventstore
    def test_add_item_to_seeded_cart(self):
        """Command that adds a child entity after seeding works."""
        cid = str(uuid4())
        created = CartCreated(cart_id=cid, owner="Charlie")

        result = given(Cart, created).process(
            AddItemToCart(cart_id=cid, product="Book", qty=3)
        )

        assert result.accepted
        assert len(result.items) == 1
        assert result.items[0].product == "Book"
        assert result.items[0].qty == 3
        assert ItemAddedToCart in result.events


# ---------------------------------------------------------------------------
# Tests: Multiple given events building state
# ---------------------------------------------------------------------------
class TestCumulativeState:
    @pytest.mark.eventstore
    def test_balance_reflects_all_given_events(self):
        """Aggregate state accumulated over multiple given events
        is correct before the command runs."""
        aid = str(uuid4())
        opened = AccountOpened(account_id=aid, holder="Dave", balance=100.0)
        dep1 = DepositMade(account_id=aid, amount=50.0)
        dep2 = DepositMade(account_id=aid, amount=25.0)

        result = given(Account, opened, dep1, dep2).process(
            MakeWithdrawal(account_id=aid, amount=10.0)
        )

        assert result.accepted
        # 100 + 50 + 25 - 10 = 165
        assert result.balance == 165.0

    @pytest.mark.eventstore
    def test_rejection_based_on_cumulative_state(self):
        """Command rejection depends on state from all given events."""
        aid = str(uuid4())
        opened = AccountOpened(account_id=aid, holder="Eve", balance=50.0)

        result = given(Account, opened).process(
            MakeWithdrawal(account_id=aid, amount=100.0)
        )

        assert result.rejected
        assert "Insufficient funds" in str(result.rejection)
        assert result.balance == 50.0  # Pre-command state

    @pytest.mark.eventstore
    def test_after_builds_on_given(self):
        """State from .after() is additive to the original given events."""
        aid = str(uuid4())
        opened = AccountOpened(account_id=aid, holder="Frank", balance=200.0)
        deposit = DepositMade(account_id=aid, amount=100.0)

        result = (
            given(Account, opened)
            .after(deposit)
            .process(MakeWithdrawal(account_id=aid, amount=250.0))
        )

        assert result.accepted
        # 200 + 100 - 250 = 50
        assert result.balance == 50.0


# ---------------------------------------------------------------------------
# Tests: Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    @pytest.mark.eventstore
    def test_already_cancelled_rejection(self):
        """Double-cancellation is rejected."""
        aid = str(uuid4())
        opened = AccountOpened(account_id=aid, holder="Grace", balance=100.0)
        withdrawn = WithdrawalMade(account_id=aid, amount=100.0)

        # Withdraw all, then try to withdraw more
        result = given(Account, opened, withdrawn).process(
            MakeWithdrawal(account_id=aid, amount=1.0)
        )

        assert result.rejected

    @pytest.mark.eventstore
    def test_checkout_empty_cart_rejected(self):
        """Cannot checkout a cart with no items."""
        cid = str(uuid4())
        created = CartCreated(cart_id=cid, owner="Heidi")

        result = given(Cart, created).process(CheckoutCart(cart_id=cid))

        assert result.rejected
        assert "empty cart" in str(result.rejection).lower()

    @pytest.mark.eventstore
    def test_already_paid_invoice_rejected(self):
        """Cannot pay an already-paid invoice."""
        iid = str(uuid4())
        created = InvoiceCreated(invoice_id=iid, total_amount=100.0)
        paid = InvoicePaid(invoice_id=iid)

        result = given(Invoice, created, paid).process(PayInvoice(invoice_id=iid))

        assert result.rejected
        assert "Already paid" in str(result.rejection)
