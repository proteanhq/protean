# --8<-- [start:full]
"""Chapter 16: Message Tracing

Demonstrates how to use correlation IDs and causation trees to trace the flow
of commands and events through the system.  Every command processed by
``domain.process()`` can carry an explicit ``correlation_id`` that propagates
to all downstream events and commands in the causal chain.  The event store
provides ``build_causation_tree(correlation_id)`` to reconstruct this chain
programmatically.
"""

from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.port.event_store import CausationNode
from protean.utils.eventing import Message
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:aggregate]
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


@domain.aggregate(event_sourced=True)
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

    def deposit(self, amount: float, reference: str | None = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Deposit amount must be positive"]})
        self.raise_(
            DepositMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
            )
        )

    def withdraw(self, amount: float, reference: str | None = None) -> None:
        if amount <= 0:
            raise ValidationError({"amount": ["Withdrawal amount must be positive"]})
        self.raise_(
            WithdrawalMade(
                account_id=str(self.id),
                amount=amount,
                reference=reference,
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


# --8<-- [end:aggregate]
# --8<-- [start:events]
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


# --8<-- [end:events]
# --8<-- [start:compliance_handler]
@domain.event_handler(part_of=Account)
class ComplianceAlertHandler:
    @handle(DepositMade)
    def on_large_deposit(self, event: DepositMade):
        if event.amount >= 10000:
            print(
                f"  [COMPLIANCE] Large deposit alert: "
                f"${event.amount:.2f} into account {event.account_id}"
            )

    @handle(WithdrawalMade)
    def on_large_withdrawal(self, event: WithdrawalMade):
        if event.amount >= 5000:
            print(
                f"  [COMPLIANCE] Large withdrawal alert: "
                f"${event.amount:.2f} from account {event.account_id}"
            )


# --8<-- [end:compliance_handler]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:correlated_deposit]
def make_large_deposit(account_id: str) -> None:
    domain.process(
        MakeDeposit(
            account_id=account_id,
            amount=15_000.00,
            reference="DEP-9921",
        ),
        correlation_id="audit-trail-dep-9921",
    )


# --8<-- [end:correlated_deposit]
# --8<-- [start:programmatic_tracing]
def trace(
    message_id: str,
) -> tuple[list[Message], list[Message], CausationNode | None]:
    event_store = domain.event_store.store

    # Walk UP from a message to the root command
    chain = event_store.trace_causation(message_id)

    # Walk DOWN from a message to all its effects
    effects = event_store.trace_effects(message_id, recursive=True)

    # Build the full tree for a correlation ID
    tree = event_store.build_causation_tree("audit-trail-dep-9921")

    return chain, effects, tree


# --8<-- [end:programmatic_tracing]
# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account with an explicit correlation_id for tracing
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=5000.00,
            ),
            correlation_id="audit-trail-dep-9921",
        )
        print(f"Account opened: {account_id}")

        # Make a large deposit using the same correlation_id
        make_large_deposit(account_id)
        print("Deposit of $15,000.00 made")

        # Build the causation tree for the correlation ID
        tree = domain.event_store.store.build_causation_tree("audit-trail-dep-9921")

        if tree:
            print("\n=== Causation Tree ===")
            print(f"Root: {tree.message_type} ({tree.kind})")
            print(f"  Stream: {tree.stream}")

            def print_children(node, indent=1):
                for child in node.children:
                    prefix = "  " * indent
                    print(f"{prefix}-> {child.message_type} ({child.kind})")
                    print(f"{prefix}   Stream: {child.stream}")
                    print_children(child, indent + 1)

            print_children(tree)

            # Walk up and down from the opening command
            chain, effects, _ = trace(tree.message_id)
            print(f"\nChain to root: {[m.metadata.headers.type for m in chain]}")
            print(f"Effects: {[m.metadata.headers.type for m in effects]}")

        # Verify final balance
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nFinal balance: ${account.balance:.2f}")

        assert account.balance == 20000.00  # 5000 + 15000
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
