# --8<-- [start:full]
from protean import Domain, apply, handle, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, Identifier, String
from protean.utils.globals import current_domain

domain = Domain("fidelis")


# --8<-- [start:account_events]
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


# --8<-- [end:account_events]
# --8<-- [start:account_aggregate]
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


# --8<-- [end:account_aggregate]
# --8<-- [start:transfer_events]
@domain.event(part_of="Transfer")
class TransferInitiated:
    transfer_id: Identifier(required=True)
    source_account_id: String(required=True)
    destination_account_id: String(required=True)
    amount: Float(required=True)


@domain.event(part_of="Transfer")
class TransferCompleted:
    transfer_id: Identifier(required=True)


@domain.event(part_of="Transfer")
class TransferFailed:
    transfer_id: Identifier(required=True)
    reason: String(required=True)


# --8<-- [end:transfer_events]
# --8<-- [start:transfer_aggregate]
@domain.aggregate(is_event_sourced=True)
class Transfer:
    source_account_id: String(max_length=50, required=True)
    destination_account_id: String(max_length=50, required=True)
    amount: Float(required=True)
    status: String(max_length=20, default="INITIATED")

    @classmethod
    def initiate(
        cls,
        source_account_id: str,
        destination_account_id: str,
        amount: float,
    ):
        transfer = cls._create_new()
        transfer.raise_(
            TransferInitiated(
                transfer_id=str(transfer.id),
                source_account_id=source_account_id,
                destination_account_id=destination_account_id,
                amount=amount,
            )
        )
        return transfer

    def complete(self) -> None:
        self.raise_(TransferCompleted(transfer_id=str(self.id)))

    def fail(self, reason: str) -> None:
        self.raise_(TransferFailed(transfer_id=str(self.id), reason=reason))

    @apply
    def on_transfer_initiated(self, event: TransferInitiated):
        self.id = event.transfer_id
        self.source_account_id = event.source_account_id
        self.destination_account_id = event.destination_account_id
        self.amount = event.amount
        self.status = "INITIATED"

    @apply
    def on_transfer_completed(self, event: TransferCompleted):
        self.status = "COMPLETED"

    @apply
    def on_transfer_failed(self, event: TransferFailed):
        self.status = "FAILED"


# --8<-- [end:transfer_aggregate]
# --8<-- [start:transfer_commands]
@domain.command(part_of=Transfer)
class InitiateTransfer:
    source_account_id: String(required=True)
    destination_account_id: String(required=True)
    amount: Float(required=True)


@domain.command(part_of=Transfer)
class CompleteTransfer:
    transfer_id: Identifier(required=True)


@domain.command(part_of=Transfer)
class FailTransfer:
    transfer_id: Identifier(required=True)
    reason: String(required=True)


# --8<-- [end:transfer_commands]
# --8<-- [start:transfer_handler]
@domain.command_handler(part_of=Transfer)
class TransferCommandHandler:
    @handle(InitiateTransfer)
    def handle_initiate_transfer(self, command: InitiateTransfer):
        transfer = Transfer.initiate(
            source_account_id=command.source_account_id,
            destination_account_id=command.destination_account_id,
            amount=command.amount,
        )
        current_domain.repository_for(Transfer).add(transfer)
        return str(transfer.id)

    @handle(CompleteTransfer)
    def handle_complete_transfer(self, command: CompleteTransfer):
        repo = current_domain.repository_for(Transfer)
        transfer = repo.get(command.transfer_id)
        transfer.complete()
        repo.add(transfer)

    @handle(FailTransfer)
    def handle_fail_transfer(self, command: FailTransfer):
        repo = current_domain.repository_for(Transfer)
        transfer = repo.get(command.transfer_id)
        transfer.fail(reason=command.reason)
        repo.add(transfer)


# --8<-- [end:transfer_handler]
# --8<-- [start:process_manager]
@domain.process_manager(stream_categories=["fidelis::transfer", "fidelis::account"])
class FundsTransferPM:
    transfer_id: Identifier()
    source_account_id: String()
    destination_account_id: String()
    amount: Float()
    status: String(default="new")

    @handle(TransferInitiated, start=True, correlate="transfer_id")
    def on_transfer_initiated(self, event: TransferInitiated) -> None:
        self.transfer_id = event.transfer_id
        self.source_account_id = event.source_account_id
        self.destination_account_id = event.destination_account_id
        self.amount = event.amount
        self.status = "withdrawing"

        # Withdraw from source account
        current_domain.process(
            MakeWithdrawal(
                account_id=event.source_account_id,
                amount=event.amount,
                reference=f"transfer:{event.transfer_id}",
            )
        )

    @handle(WithdrawalMade, correlate="account_id")
    def on_withdrawal_made(self, event: WithdrawalMade) -> None:
        self.status = "depositing"

        # Deposit into destination account
        current_domain.process(
            MakeDeposit(
                account_id=self.destination_account_id,
                amount=self.amount,
                reference=f"transfer:{self.transfer_id}",
            )
        )

    @handle(DepositMade, correlate="account_id")
    def on_deposit_made(self, event: DepositMade) -> None:
        self.status = "completing"

        # Mark transfer as complete
        current_domain.process(CompleteTransfer(transfer_id=self.transfer_id))

    @handle(TransferCompleted, correlate="transfer_id")
    def on_transfer_completed(self, event: TransferCompleted) -> None:
        self.status = "completed"
        self.mark_as_complete()

    @handle(TransferFailed, correlate="transfer_id", end=True)
    def on_transfer_failed(self, event: TransferFailed) -> None:
        self.status = "failed"


# --8<-- [end:process_manager]
domain.init(traverse=False)
domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"


# --8<-- [start:usage]
if __name__ == "__main__":
    with domain.domain_context():
        # Open two accounts
        alice_id = domain.process(
            OpenAccount(
                account_number="ACC-001",
                holder_name="Alice Johnson",
                opening_deposit=10000.00,
            )
        )
        bob_id = domain.process(
            OpenAccount(
                account_number="ACC-002",
                holder_name="Bob Smith",
                opening_deposit=5000.00,
            )
        )
        print(f"Alice's account: {alice_id}")
        print(f"Bob's account: {bob_id}")

        # Initiate a transfer of $3000 from Alice to Bob
        transfer_id = domain.process(
            InitiateTransfer(
                source_account_id=alice_id,
                destination_account_id=bob_id,
                amount=3000.00,
            )
        )
        print(f"\nTransfer initiated: {transfer_id}")

        # The transfer aggregate is created with INITIATED status
        transfer_repo = current_domain.repository_for(Transfer)
        transfer = transfer_repo.get(transfer_id)
        print(f"Transfer status: {transfer.status}")
        assert transfer.status == "INITIATED"

        # The process manager coordinates the remaining steps
        # (withdrawal, deposit, completion) when the server runs:
        #   $ protean server --domain=fidelis
        #
        # With the server running, the PM would:
        # 1. React to TransferInitiated → withdraw from Alice
        # 2. React to WithdrawalMade → deposit into Bob
        # 3. React to DepositMade → complete the transfer
        #
        # Final state after PM completes:
        #   Alice: $7,000 (10000 - 3000)
        #   Bob:   $8,000 (5000 + 3000)
        #   Transfer: COMPLETED

        print("\nAll checks passed!")
# --8<-- [end:usage]
# --8<-- [end:full]
