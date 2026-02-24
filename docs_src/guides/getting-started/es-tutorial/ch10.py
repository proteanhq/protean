# --8<-- [start:full]
from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, HasMany, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:entity]
@domain.entity(part_of="Account")
class AuthorizedSignatory:
    name: String(max_length=100, required=True)
    role: String(max_length=50, default="OPERATOR")
    email: String(max_length=255, required=True)


# --8<-- [end:entity]
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


# --8<-- [start:signatory_events]
@domain.event(part_of="Account")
class SignatoryAdded:
    account_id: Identifier(required=True)
    signatory_name: String(required=True)
    signatory_role: String(required=True)
    signatory_email: String(required=True)


@domain.event(part_of="Account")
class SignatoryRemoved:
    account_id: Identifier(required=True)
    signatory_email: String(required=True)


# --8<-- [end:signatory_events]


# --8<-- [end:events]
# --8<-- [start:aggregate]
@domain.aggregate(is_event_sourced=True)
class Account:
    account_number: String(max_length=20, required=True)
    holder_name: String(max_length=100, required=True)
    balance: Float(default=0.0)
    status: String(max_length=20, default="ACTIVE")
    signatories: HasMany(AuthorizedSignatory)

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

    def add_signatory(self, name: str, email: str, role: str = "OPERATOR") -> None:
        self.raise_(
            SignatoryAdded(
                account_id=str(self.id),
                signatory_name=name,
                signatory_role=role,
                signatory_email=email,
            )
        )

    def remove_signatory(self, email: str) -> None:
        signatory = next((s for s in self.signatories if s.email == email), None)
        if signatory is None:
            raise ValidationError(
                {"signatories": [f"No signatory found with email '{email}'"]}
            )
        self.raise_(
            SignatoryRemoved(
                account_id=str(self.id),
                signatory_email=email,
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
    def on_signatory_added(self, event: SignatoryAdded):
        self.add_signatories(
            AuthorizedSignatory(
                name=event.signatory_name,
                role=event.signatory_role,
                email=event.signatory_email,
            )
        )

    @apply
    def on_signatory_removed(self, event: SignatoryRemoved):
        signatory = next(
            (s for s in self.signatories if s.email == event.signatory_email), None
        )
        if signatory:
            self.remove_signatories(signatory)


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
class AddSignatory:
    account_id: Identifier(required=True)
    name: String(required=True)
    email: String(required=True)
    role: String(default="OPERATOR")


@domain.command(part_of=Account)
class RemoveSignatory:
    account_id: Identifier(required=True)
    email: String(required=True)


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

    @handle(AddSignatory)
    def handle_add_signatory(self, command: AddSignatory):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.add_signatory(
            name=command.name,
            email=command.email,
            role=command.role,
        )
        repo.add(account)

    @handle(RemoveSignatory)
    def handle_remove_signatory(self, command: RemoveSignatory):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        account.remove_signatory(email=command.email)
        repo.add(account)


# --8<-- [end:command_handler]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open an account
        account_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=5000.00,
            )
        )
        print(f"Account opened: {account_id}")

        # Add a signatory
        domain.process(
            AddSignatory(
                account_id=account_id,
                name="Bob Smith",
                email="bob@fidelis.com",
                role="MANAGER",
            )
        )
        print("Signatory added: Bob Smith")

        # Add another signatory
        domain.process(
            AddSignatory(
                account_id=account_id,
                name="Carol Davis",
                email="carol@fidelis.com",
                role="OPERATOR",
            )
        )
        print("Signatory added: Carol Davis")

        # Verify signatories
        repo = current_domain.repository_for(Account)
        account = repo.get(account_id)
        print(f"\nAccount: {account.account_number}")
        print(f"Holder: {account.holder_name}")
        print(f"Balance: ${account.balance:.2f}")
        print(f"Signatories ({len(account.signatories)}):")
        for sig in account.signatories:
            print(f"  - {sig.name} ({sig.role}) <{sig.email}>")

        assert len(account.signatories) == 2
        assert account.signatories[0].name == "Bob Smith"

        # Remove a signatory
        domain.process(
            RemoveSignatory(
                account_id=account_id,
                email="bob@fidelis.com",
            )
        )
        print("\nSignatory removed: Bob Smith")

        # Verify removal
        account = repo.get(account_id)
        print(f"Signatories ({len(account.signatories)}):")
        for sig in account.signatories:
            print(f"  - {sig.name} ({sig.role}) <{sig.email}>")

        assert len(account.signatories) == 1
        assert account.signatories[0].name == "Carol Davis"
        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
