# Temporal Queries for Audit, Debugging, and Compliance

## The Problem

Event-sourced systems store the complete history of every aggregate as an
ordered sequence of events. This history is one of the key selling points
of event sourcing -- in theory, you can answer questions like "what was
this account's balance when the fraudulent transaction occurred?" or "what
did this customer's profile look like when we approved the loan?"

In practice, teams rarely operationalize this capability. When an incident
investigation, compliance audit, or customer support case requires
reconstructing past state, engineers fall back to ad-hoc approaches:

```python
# Ad-hoc approach: manually read and replay events
from protean.utils.globals import current_domain


def investigate_account_state(account_id: str, target_version: int):
    """Quick-and-dirty reconstruction for an incident investigation."""
    store = current_domain.event_store.store
    raw_events = store._read(f"account-{account_id}")

    state = {}
    for i, raw_event in enumerate(raw_events):
        if i > target_version:
            break
        state.update(raw_event["data"])

    return state
```

This approach has several problems:

- **Bypasses the domain model.** The reconstruction logic does not use the
  aggregate's `@apply` handlers, so it misses computed fields, derived
  state, and business rules.

- **Duplicates reconstruction logic.** Every investigation requires writing
  new replay code that is subtly different and never tested.

- **Produces mutable objects.** Nothing prevents accidentally persisting
  changes to a historical snapshot, corrupting the event stream.

- **Cannot be exposed safely.** Customer support and compliance teams need
  self-service access, but ad-hoc scripts require engineering time.

The underlying problem: **the event store contains complete history, but
the application has no first-class API for querying it.**

---

## The Pattern

Use the event-sourced repository's `at_version` and `as_of` parameters as
**first-class query operations**. These are not debugging utilities -- they
are production-grade API parameters that reconstruct aggregate state at a
specific point in history.

Two temporal dimensions are supported:

- **`at_version=N`** reconstructs the aggregate after the Nth event
  (0-indexed). Version 0 is the state after the first event. This is
  useful when you know the exact event position -- for example, "show me
  the account state before the suspicious transaction at version 47."

- **`as_of=datetime`** reconstructs the aggregate as of a point in time.
  Only events written on or before the timestamp are applied. This is
  useful for calendar-based queries -- for example, "show me the account
  state as of the end-of-quarter reporting date."

The returned aggregate is **read-only**. Protean marks it with
`_is_temporal=True`, and any attempt to call `raise_()` on it raises
`IncorrectUsageError`. This makes temporal aggregates safe to expose
through API endpoints, customer support tools, and compliance dashboards
without risk of accidental mutation.

Key behaviors:

1. **Identity map bypass.** Temporal queries always bypass the Unit of
   Work's identity map. Loading the same aggregate at version 5 and
   version 10 in the same transaction returns two distinct objects.

2. **Snapshot awareness.** `at_version` leverages existing snapshots when
   the snapshot version is at or below the requested version. `as_of`
   skips snapshots entirely and replays from position 0.

3. **Mutual exclusivity.** You cannot specify both `at_version` and
   `as_of` in the same call. They represent different dimensions of
   history and combining them would be ambiguous.

Design temporal query endpoints for three categories of consumers:

- **Compliance audits**: "Show me this customer's KYC status as of the
  date we approved the transaction."
- **Customer support**: "What was this order's state when the customer
  called to complain?"
- **Incident investigation**: "Reconstruct this account at version 47 to
  determine what changed between versions 46 and 48."

---

## Applying the Pattern

### The event-sourced aggregate

A financial compliance domain with an `Account` aggregate that tracks
identity verification and transaction limits:

```python
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from protean import Domain, apply
from protean.fields import Auto, DateTime, Float, Identifier, String

compliance = Domain(__file__, "Compliance")


class VerificationStatus(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    SUSPENDED = "suspended"


@compliance.event(part_of="Account")
class AccountOpened:
    account_id = Identifier()
    holder_name = String()
    email = String()


@compliance.event(part_of="Account")
class IdentityVerified:
    account_id = Identifier()
    verification_level = String()
    verified_at = DateTime()
    verified_by = String()


@compliance.event(part_of="Account")
class TransactionLimitChanged:
    account_id = Identifier()
    previous_limit = Float()
    new_limit = Float()
    reason = String()


@compliance.event(part_of="Account")
class AccountSuspended:
    account_id = Identifier()
    reason = String()
    suspended_at = DateTime()


@compliance.aggregate(is_event_sourced=True)
class Account:
    account_id = Auto(identifier=True)
    holder_name = String()
    email = String()
    verification_status = String(
        choices=VerificationStatus,
        default=VerificationStatus.UNVERIFIED.value,
    )
    verification_level = String()
    verified_at = DateTime()
    verified_by = String()
    daily_transaction_limit = Float(default=1000.00)
    status = String(default="active")
    suspended_at = DateTime()
    suspension_reason = String()

    @classmethod
    def open(cls, account_id: str, holder_name: str, email: str) -> Account:
        account = cls(account_id=account_id)
        account.raise_(AccountOpened(
            account_id=account_id, holder_name=holder_name, email=email,
        ))
        return account

    def verify_identity(self, level: str, verifier: str) -> None:
        self.raise_(IdentityVerified(
            account_id=self.account_id, verification_level=level,
            verified_at=datetime.now(timezone.utc), verified_by=verifier,
        ))

    def change_transaction_limit(self, new_limit: float, reason: str) -> None:
        self.raise_(TransactionLimitChanged(
            account_id=self.account_id, previous_limit=self.daily_transaction_limit,
            new_limit=new_limit, reason=reason,
        ))

    def suspend(self, reason: str) -> None:
        self.raise_(AccountSuspended(
            account_id=self.account_id, reason=reason,
            suspended_at=datetime.now(timezone.utc),
        ))

    # --- @apply handlers for event sourcing ---

    @apply
    def on_opened(self, event: AccountOpened) -> None:
        self.account_id = event.account_id
        self.holder_name = event.holder_name
        self.email = event.email
        self.verification_status = VerificationStatus.UNVERIFIED.value
        self.daily_transaction_limit = 1000.00
        self.status = "active"

    @apply
    def on_identity_verified(self, event: IdentityVerified) -> None:
        self.verification_status = VerificationStatus.VERIFIED.value
        self.verification_level = event.verification_level
        self.verified_at = event.verified_at
        self.verified_by = event.verified_by

    @apply
    def on_transaction_limit_changed(self, event: TransactionLimitChanged) -> None:
        self.daily_transaction_limit = event.new_limit

    @apply
    def on_suspended(self, event: AccountSuspended) -> None:
        self.status = "suspended"
        self.verification_status = VerificationStatus.SUSPENDED.value
        self.suspended_at = event.suspended_at
        self.suspension_reason = event.reason
```

### Basic temporal query with `at_version`

Reconstruct the account after a specific number of events. Version 0 is
the state after the first event. Version 1 adds the second event, etc.

```python
from protean.utils.globals import current_domain

# Account history: v0=Opened, v1=Verified, v2=LimitRaised(50k),
#                  v3=LimitRaised(100k), v4=Suspended
repo = current_domain.repository_for(Account)

# Current state
account_now = repo.get("acct-1001")
assert account_now.status == "suspended"
assert account_now._version == 4

# State at version 1: just verified, limit still at default
account_v1 = repo.get("acct-1001", at_version=1)
assert account_v1.verification_status == "verified"
assert account_v1.daily_transaction_limit == 1000.00
assert account_v1.status == "active"
assert account_v1._version == 1
```

### Point-in-time query with `as_of`

Reconstruct the account as it existed at a specific timestamp. Only events
written on or before that moment are applied.

```python
from datetime import datetime, timezone

# Reconstruct the account as of the end-of-quarter reporting date
quarter_end = datetime(2025, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
account_at_quarter = repo.get("acct-1001", as_of=quarter_end)

print(f"Verification: {account_at_quarter.verification_status}")
print(f"Limit: {account_at_quarter.daily_transaction_limit}")
print(f"Version at that time: {account_at_quarter._version}")
```

!!! note "`as_of` and timezone handling"
    Protean normalizes timezone-naive and timezone-aware timestamps before
    comparison. Pass your `as_of` timestamp in UTC for consistent results.

### Application service exposing temporal queries

Wrap temporal queries in an application service that provides a clean API
for compliance and support teams:

```python
from protean import use_case
from protean.core.application_service import BaseApplicationService
from protean.utils.globals import current_domain


@compliance.application_service(part_of=Account)
class AccountAuditService(BaseApplicationService):

    @use_case
    def get_account_at_version(self, account_id: str, version: int) -> Account:
        """Reconstruct an account at a specific event version."""
        repo = current_domain.repository_for(Account)
        return repo.get(account_id, at_version=version)

    @use_case
    def get_account_as_of(self, account_id: str, timestamp: datetime) -> Account:
        """Reconstruct an account as of a specific date and time."""
        repo = current_domain.repository_for(Account)
        return repo.get(account_id, as_of=timestamp)

    @use_case
    def compare_account_versions(
        self, account_id: str, version_a: int, version_b: int
    ) -> dict:
        """Compare an account's state at two different versions."""
        repo = current_domain.repository_for(Account)
        account_a = repo.get(account_id, at_version=version_a)
        account_b = repo.get(account_id, at_version=version_b)

        changes = {}
        for field_name in account_a.meta_.attributes:
            val_a = getattr(account_a, field_name, None)
            val_b = getattr(account_b, field_name, None)
            if val_a != val_b:
                changes[field_name] = {"version_a": val_a, "version_b": val_b}

        return {
            "account_id": account_id,
            "version_a": version_a,
            "version_b": version_b,
            "changes": changes,
        }
```

### API endpoint for audit trail

Expose temporal queries through a REST API so compliance and support teams
can self-serve:

```python
from fastapi import FastAPI, HTTPException, Query
from protean.exceptions import ObjectNotFoundError

app = FastAPI()


@app.get("/accounts/{account_id}/at-version/{version}")
async def get_account_at_version(account_id: str, version: int):
    try:
        account = AccountAuditService().get_account_at_version(account_id, version)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "account_id": account.account_id,
        "verification_status": account.verification_status,
        "daily_transaction_limit": account.daily_transaction_limit,
        "version": account._version,
        "is_temporal": account._is_temporal,
    }


@app.get("/accounts/{account_id}/as-of")
async def get_account_as_of(
    account_id: str,
    timestamp: str = Query(..., description="ISO-8601 timestamp"),
):
    try:
        account = AccountAuditService().get_account_as_of(
            account_id, datetime.fromisoformat(timestamp)
        )
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return {
        "account_id": account.account_id,
        "verification_status": account.verification_status,
        "daily_transaction_limit": account.daily_transaction_limit,
        "version": account._version,
        "is_temporal": account._is_temporal,
    }
```

### Read-only safety

Protean sets `_is_temporal=True` on every aggregate returned by a temporal
query. The `raise_()` method checks this flag before accepting new events:

```python
from protean.exceptions import IncorrectUsageError

account_v1 = repo.get("acct-1001", at_version=1)
assert account_v1._is_temporal is True

try:
    account_v1.change_transaction_limit(999_999.00, "Attempted fraud")
except IncorrectUsageError as exc:
    print(exc)
    # "Cannot raise events on a temporally-loaded aggregate.
    #  Temporal aggregates are read-only."
```

You can safely pass temporal aggregates to serializers, API layers, and
reporting tools without defensive wrappers.

!!! warning "Read-only at the domain level, not the Python level"
    The `_is_temporal` flag prevents `raise_()` from accepting new events.
    It does **not** make the Python object immutable -- you can still set
    attributes. However, those changes will never be persisted because no
    events are raised.

### Identity map bypass

Within a Unit of Work, normal `get()` calls return the same aggregate
instance from the identity map. Temporal queries **bypass** this cache:

```python
from protean.core.unit_of_work import UnitOfWork

with UnitOfWork():
    repo = current_domain.repository_for(Account)

    account_current = repo.get("acct-1001")
    assert account_current._version == 4

    # Temporal query returns a separate, historical object
    account_v1 = repo.get("acct-1001", at_version=1)
    assert account_v1._version == 1

    # The identity map still holds the current version
    account_again = repo.get("acct-1001")
    assert account_again is account_current  # Same object
```

---

## Anti-Patterns

### Building custom replay logic

```python
# Anti-pattern: hand-rolled event replay
def get_account_at_version(account_id: str, version: int) -> dict:
    store = current_domain.event_store.store
    events = store._read(f"account-{account_id}")

    state = {}
    for i, event in enumerate(events):
        if i > version:
            break
        state.update(event["data"])

    return state
```

This bypasses the aggregate's `@apply` handlers, ignores snapshots, skips
validation, and returns a mutable dictionary instead of a proper domain
object. Use the repository's `at_version` parameter instead:

```python
account = repo.get(account_id, at_version=version)
```

### Querying the event store directly for point-in-time state

```python
# Anti-pattern: reading raw events and filtering by timestamp
def get_account_as_of(account_id: str, cutoff: datetime) -> dict:
    store = current_domain.event_store.store
    events = store._read(f"account-{account_id}")

    state = {}
    for event in events:
        if datetime.fromisoformat(event.get("time", "")) > cutoff:
            break
        state.update(event["data"])

    return state
```

This duplicates timestamp parsing, timezone normalization, and event
filtering that the event store handles internally. It also fails across
adapters (PostgreSQL returns `datetime` objects; memory returns ISO
strings). Use the repository instead:

```python
account = repo.get(account_id, as_of=cutoff)
```

### Using temporal data for writes

```python
# Anti-pattern: loading a historical version and trying to modify it
def rollback_account(account_id: str, version: int) -> None:
    repo = current_domain.repository_for(Account)
    old_account = repo.get(account_id, at_version=version)
    repo.add(old_account)  # Will fail -- _is_temporal is True
```

Temporal aggregates are read-only. If you need to "undo" a change, model
the reversal as an explicit domain operation on the **current** aggregate:

```python
# Correct: model the reversal as a new event
def restore_transaction_limit(account_id: str, version: int) -> None:
    repo = current_domain.repository_for(Account)

    # Read the historical state to learn what the limit was
    old_account = repo.get(account_id, at_version=version)
    old_limit = old_account.daily_transaction_limit

    # Apply the reversal to the current aggregate
    current_account = repo.get(account_id)
    current_account.change_transaction_limit(
        old_limit, reason=f"Restored to version {version} limit"
    )
    repo.add(current_account)
```

---

## Summary

| Capability | API | Description |
|-----------|-----|-------------|
| Version-based reconstruction | `repo.get(id, at_version=N)` | State after the Nth event (0-indexed) |
| Time-based reconstruction | `repo.get(id, as_of=datetime)` | State as of a specific timestamp |
| Read-only guarantee | `_is_temporal=True` | `raise_()` raises `IncorrectUsageError` |
| Identity map bypass | Automatic | Temporal queries never return cached objects |
| Snapshot awareness | `at_version` only | Leverages snapshots when version <= requested |
| Mutual exclusivity | Enforced | Cannot combine `at_version` and `as_of` |

| Use case | Recommended parameter | Example |
|----------|----------------------|---------|
| Investigate a specific event | `at_version` | "Show state before event 47" |
| Regulatory reporting | `as_of` | "Account state at quarter end" |
| Customer support | `as_of` | "State when customer called at 3:14 PM" |
| Version comparison | Two `at_version` calls | "What changed between versions 5 and 8?" |
| Incident forensics | `at_version` or `as_of` | "Reconstruct the timeline of changes" |

| Principle | Practice |
|-----------|----------|
| Temporal queries are first-class operations | Use repository parameters, not custom replay |
| Historical aggregates are read-only | Never persist or mutate temporal objects |
| Model reversals as new events | Load old state for reference, apply changes to current |
| Expose temporal queries to consumers | Build API endpoints for audit, support, compliance |
| Use the right temporal dimension | `at_version` for event positions, `as_of` for calendar time |

---

!!! tip "Related reading"
    **Concepts:**

    - [Event Sourcing](../concepts/architecture/event-sourcing.md) -- Deriving state from event replay.

    **Guides:**

    - [Temporal Queries](../guides/change-state/temporal-queries.md) -- How to use at_version and as_of.
    - [`protean events`](../reference/cli/data/events.md) -- Inspect event streams and aggregate history.
