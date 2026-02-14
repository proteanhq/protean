from datetime import datetime, timezone
from enum import Enum

from protean import Domain
from typing import Annotated
from pydantic import Field

domain = Domain()


def utc_now():
    return datetime.now(timezone.utc)


class AccountType(Enum):
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"


@domain.aggregate
class Account:
    account_number: int = Field(json_schema_extra={"unique": True})
    account_type: Annotated[AccountType, Field(max_length=7)]
    balance: float = 0.0
    opened_at: datetime = utc_now
