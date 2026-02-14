from datetime import datetime, timezone
from enum import Enum

from protean import Domain
from protean.fields import DateTime, Float, Integer, String

domain = Domain()


def utc_now():
    return datetime.now(timezone.utc)


class AccountType(Enum):
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"


@domain.aggregate
class Account:
    account_number: Integer(required=True, unique=True)
    account_type: String(required=True, max_length=7, choices=AccountType)
    balance: Float(default=0.0)
    opened_at: DateTime(default=utc_now)
