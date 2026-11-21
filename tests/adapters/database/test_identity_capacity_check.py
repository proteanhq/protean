"""``domain.init()`` refuses an identity a SQL provider's column cannot hold.

The check lives with the SQLAlchemy adapter, which is an optional extra. These
tests cover the registry side of the check, which needs no SQL database.
"""

import sys

from protean.core.aggregate import BaseAggregate
from protean.fields import String


class Note(BaseAggregate):
    title = String(max_length=50)


def test_without_sqlalchemy_the_check_is_skipped(test_domain, monkeypatch):
    """With SQLAlchemy not installed no SQL provider exists, so nothing is checked."""
    test_domain.register(Note)
    test_domain.init(traverse=False)
    monkeypatch.setitem(sys.modules, "protean.adapters.database.sqlalchemy", None)

    assert test_domain.databases.validate_identity_capacity() is None
