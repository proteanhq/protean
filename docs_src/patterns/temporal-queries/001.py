# --8<-- [start:aggregate]
from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum

from protean import Domain, apply
from protean.fields import Auto, DateTime, Float, Identifier, String

compliance = Domain(name="Compliance")


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


@compliance.aggregate(event_sourced=True)
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
        account.raise_(
            AccountOpened(
                account_id=account_id,
                holder_name=holder_name,
                email=email,
            )
        )
        return account

    def verify_identity(self, level: str, verifier: str) -> None:
        self.raise_(
            IdentityVerified(
                account_id=self.account_id,
                verification_level=level,
                verified_at=datetime.now(UTC),
                verified_by=verifier,
            )
        )

    def change_transaction_limit(self, new_limit: float, reason: str) -> None:
        self.raise_(
            TransactionLimitChanged(
                account_id=self.account_id,
                previous_limit=self.daily_transaction_limit,
                new_limit=new_limit,
                reason=reason,
            )
        )

    def suspend(self, reason: str) -> None:
        self.raise_(
            AccountSuspended(
                account_id=self.account_id,
                reason=reason,
                suspended_at=datetime.now(UTC),
            )
        )

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


# --8<-- [end:aggregate]


# --8<-- [start:history]
from protean.utils.globals import current_domain


def record_account_history(account_id: str = "acct-1001") -> None:
    repo = current_domain.repository_for(Account)

    # v0: opened, v1: verified
    account = Account.open(account_id, "Jane Doe", "jane@example.com")
    account.verify_identity("full", verifier="kyc-team")
    repo.add(account)

    # v2 and v3: the limit is raised twice
    account = repo.get(account_id)
    account.change_transaction_limit(50_000.00, reason="Business account")
    account.change_transaction_limit(100_000.00, reason="Annual review")
    repo.add(account)

    # v4: suspended
    account = repo.get(account_id)
    account.suspend(reason="Suspicious activity")
    repo.add(account)


# --8<-- [end:history]


# --8<-- [start:at_version]
def inspect_account_at_version_1() -> None:
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


# --8<-- [end:at_version]


# --8<-- [start:as_of]
def account_at_quarter_end(quarter_end: datetime) -> Account:
    # For example: datetime(2025, 12, 31, 23, 59, 59, tzinfo=UTC)
    repo = current_domain.repository_for(Account)
    account_at_quarter = repo.get("acct-1001", as_of=quarter_end)

    print(f"Verification: {account_at_quarter.verification_status}")
    print(f"Limit: {account_at_quarter.daily_transaction_limit}")
    print(f"Version at that time: {account_at_quarter._version}")
    return account_at_quarter


# --8<-- [end:as_of]


# --8<-- [start:audit_service]
from protean import use_case
from protean.core.application_service import BaseApplicationService
from protean.utils.reflection import attributes


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
        for field_name in attributes(account_a):
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


# --8<-- [end:audit_service]


# --8<-- [start:api]
from fastapi import FastAPI, HTTPException, Query

from protean.exceptions import ObjectNotFoundError
from protean.integrations.fastapi import DomainContextMiddleware

app = FastAPI()
app.add_middleware(DomainContextMiddleware, route_domain_map={"/": compliance})


@app.get("/accounts/{account_id}/at-version/{version}")
async def get_account_at_version(account_id: str, version: int):
    try:
        account = AccountAuditService().get_account_at_version(account_id, version)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

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
        as_of = datetime.fromisoformat(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        account = AccountAuditService().get_account_as_of(account_id, as_of)
    except ObjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "account_id": account.account_id,
        "verification_status": account.verification_status,
        "daily_transaction_limit": account.daily_transaction_limit,
        "version": account._version,
        "is_temporal": account._is_temporal,
    }


# --8<-- [end:api]


# --8<-- [start:read_only]
from protean.exceptions import IncorrectUsageError


def try_to_change_a_past_version() -> None:
    repo = current_domain.repository_for(Account)
    account_v1 = repo.get("acct-1001", at_version=1)
    assert account_v1._is_temporal is True

    try:
        account_v1.change_transaction_limit(999_999.00, "Attempted fraud")
    except IncorrectUsageError as exc:
        print(exc)
        # "Cannot raise events on a temporally-loaded aggregate.
        #  Temporal aggregates are read-only."


# --8<-- [end:read_only]


# --8<-- [start:identity_map]
from protean.core.unit_of_work import UnitOfWork


def load_current_and_past_in_one_unit_of_work() -> None:
    with UnitOfWork():
        repo = current_domain.repository_for(Account)

        account_current = repo.get("acct-1001")
        assert account_current._version == 4

        account_current.change_transaction_limit(5_000.00, reason="Temporary cap")
        repo.add(account_current)  # Tracked in the identity map until commit

        # Temporal query returns a separate, historical object
        account_v1 = repo.get("acct-1001", at_version=1)
        assert account_v1._version == 1
        assert account_v1 is not account_current

        # The identity map still holds the current version
        account_again = repo.get("acct-1001")
        assert account_again is account_current  # Same object


# --8<-- [end:identity_map]


# --8<-- [start:restore]
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


# --8<-- [end:restore]

compliance.init(traverse=False)
