# --8<-- [start:full]
"""Chapter 14: Connecting to the Outside World

Demonstrates how to integrate external systems with your domain using
subscribers, event enrichers, and command enrichers.  Subscribers act as
an anti-corruption layer, translating external webhook payloads into
domain commands.  Enrichers attach cross-cutting metadata to every event
or command automatically.
"""

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:events]
@domain.event(part_of="Account")
class AccountOpened:
    account_id: Identifier(required=True)
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.event(part_of="Account")
class DepositMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class WithdrawalMade:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.event(part_of="Account")
class AccountClosed:
    account_id: Identifier(required=True)
    reason: String()


# --8<-- [end:events]
# --8<-- [start:aggregate]
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance is not None and self.balance < 0:
            raise ValidationError(
                {"balance": ["Insufficient funds: balance cannot be negative"]}
            )

    @invariant.post
    def closed_account_must_have_zero_balance(self):
        if self.status == "CLOSED" and self.balance != 0:
            raise ValidationError(
                {"status": ["Cannot close account with non-zero balance"]}
            )

    @classmethod
    def open(cls, account_number: str, holder_name: str, opening_deposit: float):
        account = cls._create_new()
        account.raise_(
            AccountOpened(
                account_id=str(account.id),
                account_number=account_number,
                holder_name=holder_name,
                opening_deposit=opening_deposit,
            )
        )
        return account

    def deposit(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Deposit amount must be positive"]})
        self.raise_(
            DepositMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
            )
        )

    def withdraw(self, amount: float, reference: str = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        self.raise_(
            WithdrawalMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
            )
        )

    def close(self, reason: str = None) -> None:
        self.raise_(
            AccountClosed(
                account_id=str(self.id),
                reason=reason,
            )
        )

    @apply
    def on_account_opened(self, event: AccountOpened):
        self.id = event.account_id
        self.account_number = event.account_number
        self.holder_name = event.holder_name
        self.balance = event.opening_deposit
        self.status = "ACTIVE"

    @apply
    def on_deposit_made(self, event: DepositMade):
        self.balance += event.amount

    @apply
    def on_withdrawal_made(self, event: WithdrawalMade):
        self.balance -= event.amount

    @apply
    def on_account_closed(self, event: AccountClosed):
        self.status = "CLOSED"


# --8<-- [end:aggregate]
# --8<-- [start:commands]
@domain.command(part_of=Account)
class OpenAccount:
    account_number: String(required=True)
    holder_name: String(required=True)
    opening_deposit: Float(required=True)


@domain.command(part_of=Account)
class MakeDeposit:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class MakeWithdrawal:
    account_id: Identifier(required=True)
    amount: Float(required=True)
    reference: String()


@domain.command(part_of=Account)
class CloseAccount:
    account_id: Identifier(required=True)
    reason: String()


# --8<-- [end:commands]
# --8<-- [start:command_handler]
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(OpenAccount)
    def handle_open_account(self, command: OpenAccount):
        account = Account.open(
            account_number=command.account_number,
            holder_name=command.holder_name,
            opening_deposit=command.opening_deposit,
        )
        current_domain.repository_for(Account).add(account)
        return str(account.id)

    @handle(MakeDeposit)
    def handle_make_deposit(self, command: MakeDeposit):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.deposit(command.amount, reference=command.reference)
        repo.add(account)

    @handle(MakeWithdrawal)
    def handle_make_withdrawal(self, command: MakeWithdrawal):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.withdraw(command.amount, reference=command.reference)
        repo.add(account)

    @handle(CloseAccount)
    def handle_close_account(self, command: CloseAccount):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.close(reason=command.reason)
        repo.add(account)


# --8<-- [end:command_handler]
# --8<-- [start:subscriber]
@domain.subscriber(stream="external::payflow")
class PayFlowWebhookSubscriber:
    """Translates PayFlow payment gateway webhooks into domain commands.

    Subscribers act as an anti-corruption layer: they receive raw dict
    payloads from an external broker stream and translate them into
    domain operations, keeping the outside world's data model out of
    the core domain.
    """

    def __call__(self, payload: dict) -> None:
        event_type = payload.get("type")

        if event_type == "payment.completed":
            account_id = payload["account_id"]
            amount = payload["amount"]
            reference = payload.get("reference", f"payflow-{payload.get('id', 'N/A')}")

            current_domain.process(
                MakeDeposit(
                    account_id=account_id,
                    amount=amount,
                    reference=reference,
                )
            )
            print(
                f"[PayFlow] Processed payment.completed: ${amount:.2f} -> {account_id}"
            )

        elif event_type == "payment.failed":
            account_id = payload.get("account_id", "unknown")
            reason = payload.get("reason", "no reason provided")
            print(f"[PayFlow] Payment failed for {account_id}: {reason}")

        else:
            print(f"[PayFlow] Ignoring unknown event type: {event_type}")

    @classmethod
    def handle_error(cls, exc: Exception, message: dict) -> None:
        """Custom error handler for PayFlow webhook processing failures."""
        print(f"[PayFlow] Error processing webhook: {exc} | Payload: {message}")


# --8<-- [end:subscriber]
# --8<-- [start:event_enricher]
@domain.event_enricher
def add_tenant_context(event, aggregate) -> dict:
    """Attach tenant context to every domain event.

    Event enrichers are called during raise_() and their return values
    are merged into the event's metadata.extensions dict.  This is
    useful for multi-tenant systems where every event needs to carry
    the tenant identifier without polluting the event's payload fields.
    """
    return {"tenant_id": "fidelis-main"}


# --8<-- [end:event_enricher]
# --8<-- [start:command_enricher]
@domain.command_enricher
def add_request_context(command) -> dict:
    """Attach request context to every command.

    Command enrichers are called during domain.process() and their
    return values are merged into the command's metadata.extensions dict.
    This is ideal for tracing: attaching request IDs, user IDs, or
    other cross-cutting concerns without adding fields to every command.
    """
    return {"request_id": "req-demo-001"}


# --8<-- [end:command_enricher]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # First, open an account so we have something to deposit into
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=1000.00,
            )
        )
        print(f"Account opened: {account_id}\n")

        # Simulate a PayFlow webhook payload for a completed payment
        webhook_payload = {
            "id": "pf-txn-42",
            "type": "payment.completed",
            "account_id": account_id,
            "amount": 250.00,
            "reference": "payflow-pf-txn-42",
        }

        # In production, the broker delivers this payload to the subscriber.
        # Here we invoke it directly to demonstrate the translation logic.
        subscriber = PayFlowWebhookSubscriber()
        subscriber(webhook_payload)

        # Simulate a failed payment webhook
        failed_payload = {
            "id": "pf-txn-43",
            "type": "payment.failed",
            "account_id": account_id,
            "reason": "insufficient funds at source",
        }
        subscriber(failed_payload)

        # Verify the deposit was processed
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nAccount balance: ${account.balance:.2f}")
        assert account.balance == 1250.00  # 1000 + 250

        # Verify enrichers attached metadata to events
        # (In a real system you'd inspect the event store messages)
        print("Event enricher registered: add_tenant_context")
        print("Command enricher registered: add_request_context")
        assert add_tenant_context in domain._event_enrichers
        assert add_request_context in domain._command_enrichers

        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
