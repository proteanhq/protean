# Domain Service Patterns

The examples on this page transfer money between two `Account` aggregates. They use these commands, events, and the aggregate:

```python
@domain.command(part_of="Account")
class TransferFunds:
    transfer_id: Identifier(required=True)
    source_id: Identifier(required=True)
    target_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command(part_of="Account")
class CreditAccount:
    transfer_id: Identifier(required=True)
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.event(part_of="Account")
class FundsDebited:
    transfer_id: Identifier(required=True)
    source_id: Identifier(required=True)
    target_id: Identifier(required=True)
    amount: Float(required=True)


@domain.aggregate
class Account:
    account_id: Identifier(identifier=True)
    balance: Float(default=0.0)
    applied_transfer_ids: List(content_type=String)

    def debit_for_transfer(self, transfer_id, target_id, amount):
        self.balance -= amount
        self.applied_transfer_ids = [*self.applied_transfer_ids, transfer_id]
        self.raise_(
            FundsDebited(
                transfer_id=transfer_id,
                source_id=self.account_id,
                target_id=target_id,
                amount=amount,
            )
        )

    def credit_for_transfer(self, transfer_id, amount):
        self.balance += amount
        self.applied_transfer_ids = [*self.applied_transfer_ids, transfer_id]
```

## Callable pattern (recommended)

The most common pattern. Instantiate with aggregates, call to execute.

```python
@domain.domain_service(part_of=[Account, Account])
class FundsTransferService:
    def __init__(self, source, target, transfer_id, amount):
        self.source = source
        self.target = target
        self.transfer_id = transfer_id
        self.amount = amount

    @invariant.pre
    def sufficient_balance(self):
        if self.source.balance < self.amount:
            raise ValidationError({"_service": ["Insufficient balance"]})

    @invariant.post
    def source_debited(self):
        if self.source.balance < 0:
            raise ValidationError({"_service": ["Source balance went negative"]})

    def __call__(self):
        # Change only the source. The target is credited through FundsDebited.
        self.source.debit_for_transfer(
            self.transfer_id, self.target.account_id, self.amount
        )
```

Usage:
```python
domain.init(traverse=False)

with domain.domain_context():
    source = Account(account_id="A-1", balance=100.0)
    target = Account(account_id="B-1", balance=0.0)

    FundsTransferService(source, target, "T-1", 40.0)()
    assert source.balance == 60.0
    assert target.balance == 0.0  # credited later, through the event
```

## You do not need the base class __init__

A plain `__init__` that stores the aggregates is enough. The pre and post invariants are wired when the service is registered with `@domain.domain_service`, so leaving out `super().__init__()` does not switch them off.

Calling `super().__init__(source, target)` still works. It stores the aggregates on `self._aggregates`, which is useful only if your code reads them from there.

## Pre and post invariants

Domain services support the same `@invariant.pre` and `@invariant.post` decorators as aggregates.

- **Pre invariants**: Run before the method: validate preconditions
- **Post invariants**: Run after the method: validate postconditions

They run around every public method of the service, and `__call__` counts as public. If one public method calls another, the invariants run again for the inner call.

Helper methods start with `_`, which keeps them unwrapped. An invariant must never call a public method: the method's wrapper runs the invariant again, which calls the method again, until Python's recursion limit stops the call.

## Wiring into command handlers

The command handler is responsible for:
1. Loading the aggregates from repositories
2. Instantiating and calling the domain service
3. Persisting the one aggregate the service changed

Both accounts are `Account` aggregates, but they are still two aggregates, so the handler persists only the source:

```python
@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(TransferFunds)
    def handle_transfer(self, command):
        repo = current_domain.repository_for(Account)
        source = repo.get(command.source_id)
        if command.transfer_id in source.applied_transfer_ids:
            return  # already debited; debiting again would take the money twice
        target = repo.get(command.target_id)

        FundsTransferService(source, target, command.transfer_id, command.amount)()

        repo.add(source)

    @handle(CreditAccount)
    def handle_credit(self, command):
        repo = current_domain.repository_for(Account)
        account = repo.get(command.account_id)
        if command.transfer_id in account.applied_transfer_ids:
            return  # already applied; crediting again would pay twice
        account.credit_for_transfer(command.transfer_id, command.amount)
        repo.add(account)
```

## Changing the second aggregate through an event

The source account raises `FundsDebited`. An event handler in the Account cluster, which owns the event, issues `CreditAccount` for the destination. Both handlers above skip a transfer id the account has already applied. A repeated `TransferFunds` does not debit the source twice, and a redelivered event does not credit the destination twice.

```python
@domain.event_handler(part_of=Account)
class CreditTransferTarget:
    @handle(FundsDebited)
    def on_funds_debited(self, event):
        current_domain.process(
            CreditAccount(
                transfer_id=event.transfer_id,
                account_id=event.target_id,
                amount=event.amount,
            )
        )
```

The service checks both accounts in one step, before the source changes. The credit is eventually consistent: it runs in its own transaction after the source commits, so for a short time the money has left the source and not yet reached the destination. If the credit fails, the debit stays committed. Nothing undoes it on its own. Undoing it takes a compensating command, for example one sent by a process manager.

The caller supplies `transfer_id` in the command. The source records it with the debit, and the event carries it to `CreditAccount`. A repeated command or a redelivered event then carries the same id, and the handler can tell it is a repeat. A `TransferFunds` that reuses the id with a different amount moves no money either. Each account checks only its own list, so the caller must give every transfer its own id. Never generate a fresh `uuid4()` in the event handler, because a redelivered event would then look like a new transfer.

`applied_transfer_ids` grows with every transfer and loads with the account each time.
