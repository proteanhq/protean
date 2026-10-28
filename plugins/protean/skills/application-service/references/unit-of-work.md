# Unit of Work in Application Services

Use case methods always execute within a `UnitOfWork` context. On a provider with transactions, a Unit of Work is one real database transaction: see [ADR-0027 (The Unit of Work is a real database transaction)](https://docs.proteanhq.com/adr/0027-unit-of-work-is-a-real-transaction/). There, every write the use case makes commits together, or none of them does.

## Automatic Wrapping

The `@use_case` decorator wraps every call in a UnitOfWork:

```python
from protean.fields import Identifier, String

@domain.aggregate
class User:
    email: String(required=True)
    name: String()

@domain.application_service(part_of=User)
class UserServices:
    @use_case
    def register_user(self, email: str, name: str) -> Identifier:
        # Implicitly inside UnitOfWork
        user = User(email=email, name=name)
        current_domain.repository_for(User).add(user)
        return user.id
```

Without the decorator, you would write the Unit of Work yourself:

```python
class UserServicesByHand:
    def register_user(self, email: str, name: str) -> Identifier:
        with UnitOfWork():
            user = User(email=email, name=name)
            current_domain.repository_for(User).add(user)
            return user.id
```

`@use_case` also logs the call, and checks for an active domain context first.

A Unit of Work needs a domain to open against, so call use cases after `domain.init()` and inside a domain context. Without one, the call raises `ConfigurationError`:

```python
domain.init(traverse=False)

with domain.domain_context():
    user_id = UserServices().register_user(email="jane@example.com", name="Jane")
```

## Transaction Semantics

### On Success
When a `@use_case` method completes without exception:
1. The Unit of Work commits, and every write the method made becomes visible to other connections
2. The domain events raised on the aggregates passed to `repo.add()` are written during the commit, to the event store and, when the outbox is enabled, to the outbox. Events raised on an aggregate that was only read are not saved

Before the commit, writes already reach the database inside the transaction. The session flushes them before each query, so reads in the same Unit of Work see them. Nothing is visible to other connections until the commit.

### On Failure
When an exception is raised inside a `@use_case` method:
1. The Unit of Work rolls back, which undoes all its writes
2. No partial state is persisted
3. The exception propagates to the caller

Steps 1 and 2 hold on providers with real transactions, such as the SQL providers ADR-0027 covers, and on the in-memory provider, which keeps writes in the Unit of Work until it commits. Elasticsearch has no transactions. There the Unit of Work logs a warning that commit and rollback are not atomic, and a rollback does not undo writes already sent.

### No Retry
`@use_case` runs the method once. A version conflict (`ExpectedVersionError`, raised when another writer changed the aggregate first) rolls back and reaches the caller like any other exception. A use case caller that wants a retry calls the method again.

Command and event handlers behave differently. On a version conflict, `@handle` re-runs the whole handler body. The default is `max_retries=3`, so the body runs up to 4 times in total, with waits between runs that double each time. Each run opens its own Unit of Work. A use case that calls `domain.process()` synchronously runs the handler inside the use case's Unit of Work, so the handler's Unit of Work joins it. There the handler does not retry: a failed run has already doomed the use case's transaction, so the conflict reaches the use case's caller.

## Scope

A Unit of Work can hold changes to several aggregates and commits them all in one transaction. "One aggregate per transaction" is a design rule, and the Unit of Work does not enforce it. Two instances of the same aggregate type count as two aggregates. [Anti-patterns](anti-patterns.md), section 2, shows the `transfer_funds` use case that breaks the rule and the version that raises an event instead.

## Nested Units of Work

A Unit of Work started while another is active joins the outer one. There are no savepoints. Only the outermost Unit of Work commits or rolls back, and a rollback inside dooms the whole transaction. So:

- A `with UnitOfWork():` inside a `@use_case` method adds nothing.
- A use case that calls another use case runs both in one transaction. The inner one does not commit on its own.

## Calling External Services

Keep calls to outside systems (email, payment APIs, HTTP) out of a use case that also writes. The call runs before the commit. If it comes after a write, the transaction stays open while it waits. Either way, a rollback cannot take the call back. [ADR-0031 (A handler method persists or calls out, never both)](https://docs.proteanhq.com/adr/0031-handlers-persist-or-call-out/) sets this rule for handlers, and the same reasoning applies to use cases. Persist in the use case, raise an event, and make the call from an event handler.

See [With Events](../assets/application_service_with_events.py) for a complete example showing events within UoW.
