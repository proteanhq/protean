"""The in-memory adapter enforces ``Index(unique=True)`` declarations.

Relational adapters reject duplicate rows via the DDL they render for a unique
index. The memory store renders no DDL, so it replicates the check in the DAO
to stay a faithful stand-in for uniqueness invariants (issue #1071). A duplicate
that violates a declared unique index raises ``ValidationError``, matching the
logical error relational adapters surface. NULLs are treated as distinct.
"""

import pytest

from protean import Index
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import Integer, String, ValueObject
from protean.utils.query import Q


def test_duplicate_insert_on_single_column_unique_index_is_rejected(test_domain):
    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100)
        name = String(max_length=50)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(email="a@example.com", name="First"))

    with pytest.raises(ValidationError) as exc:
        dao.save(Account(email="a@example.com", name="Second"))

    assert "email" in exc.value.messages
    assert "is already present" in exc.value.messages["email"][0]


def test_distinct_values_on_unique_index_are_accepted(test_domain):
    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(email="a@example.com"))
    dao.save(Account(email="b@example.com"))

    assert dao.query.all().total == 2


def test_duplicate_insert_on_composite_unique_index_is_rejected(test_domain):
    @test_domain.aggregate(indexes=[Index("message_id", "target_broker", unique=True)])
    class Message(BaseAggregate):
        message_id = String(max_length=50)
        target_broker = String(max_length=50)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Message)._dao

    dao.save(Message(message_id="m1", target_broker="default"))

    with pytest.raises(ValidationError) as exc:
        dao.save(Message(message_id="m1", target_broker="default"))

    assert "message_id_target_broker" in exc.value.messages
    assert "is already present" in exc.value.messages["message_id_target_broker"][0]


def test_composite_unique_index_allows_partial_overlap(test_domain):
    """Same first column but a different second column is a distinct tuple."""

    @test_domain.aggregate(indexes=[Index("message_id", "target_broker", unique=True)])
    class Message(BaseAggregate):
        message_id = String(max_length=50)
        target_broker = String(max_length=50)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Message)._dao

    # Mirrors the outbox fan-out: one message_id routed to two brokers.
    dao.save(Message(message_id="m1", target_broker="default"))
    dao.save(Message(message_id="m1", target_broker="external"))

    assert dao.query.all().total == 2


def test_nulls_are_distinct_on_unique_index(test_domain):
    """A unique index over a NULL value never collides (SQL NULL semantics)."""

    @test_domain.aggregate(indexes=[Index("token", unique=True)])
    class Session(BaseAggregate):
        token = String(max_length=50)  # optional — may be None

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Session)._dao

    dao.save(Session())
    dao.save(Session())  # second NULL token must be accepted

    assert dao.query.all().total == 2


def test_non_unique_index_is_not_enforced(test_domain):
    @test_domain.aggregate(indexes=[Index("status")])
    class Job(BaseAggregate):
        status = String(max_length=20)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Job)._dao

    dao.save(Job(status="pending"))
    dao.save(Job(status="pending"))

    assert dao.query.all().total == 2


def test_update_to_colliding_value_is_rejected(test_domain):
    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(email="a@example.com"))
    second = dao.save(Account(email="b@example.com"))

    with pytest.raises(ValidationError):
        dao.update(second, email="a@example.com")


def test_resaving_unchanged_row_does_not_collide_with_itself(test_domain):
    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100)
        counter = Integer(default=0)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    account = dao.save(Account(email="a@example.com"))
    # Re-save the same row with an updated non-indexed field — the row's own
    # index entry must be excluded from the collision check.
    updated = dao.update(account, counter=1)

    assert updated.counter == 1
    assert dao.query.all().total == 1


def test_unique_index_resolves_referenced_as_attribute(test_domain):
    """The index field name is mapped to the stored attribute (`referenced_as`)."""

    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100, referenced_as="email_address")

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(email="a@example.com"))

    # Records are keyed by "email_address"; enforcement must still find the
    # collision when the index declares the field name "email".
    with pytest.raises(ValidationError):
        dao.save(Account(email="a@example.com"))


def test_composite_unique_index_over_value_object_attributes(test_domain):
    """Index fields that are value-object shadow attributes resolve correctly.

    The declared index names the stored attributes (`balance_currency`,
    `balance_amount`), which are not in `fields()` — exercising the
    `_storage_key` attribute-name fallback.
    """

    @test_domain.value_object
    class Balance(BaseValueObject):
        currency = String(max_length=3)
        amount = Integer()

    @test_domain.aggregate(
        indexes=[Index("balance_currency", "balance_amount", unique=True)]
    )
    class Account(BaseAggregate):
        balance = ValueObject(Balance)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(balance=Balance(currency="USD", amount=100)))
    # A different amount is a distinct composite tuple.
    dao.save(Account(balance=Balance(currency="USD", amount=200)))

    with pytest.raises(ValidationError):
        dao.save(Account(balance=Balance(currency="USD", amount=100)))


def test_raw_index_is_skipped(test_domain):
    """`Index.from_sql` (RawIndex) declarations are ignored by enforcement."""

    @test_domain.aggregate(
        indexes=[
            Index("email", unique=True),
            Index.from_sql("postgresql", "CREATE INDEX ix_x ON account (email)"),
        ]
    )
    class Account(BaseAggregate):
        email = String(max_length=100)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    # The RawIndex has no `unique`/`fields`; the write path must not choke on it,
    # while the real unique index still rejects the duplicate.
    dao.save(Account(email="a@example.com"))
    with pytest.raises(ValidationError):
        dao.save(Account(email="a@example.com"))


def test_update_all_bypasses_unique_index_enforcement(test_domain):
    """Documents the scope boundary: bulk `_update_all` is not guarded.

    Row-at-a-time `_create`/`_update` (behind `repository.add`/`save`) enforce
    unique indexes; the low-level bulk escape hatch deliberately does not.
    """

    @test_domain.aggregate(indexes=[Index("email", unique=True)])
    class Account(BaseAggregate):
        email = String(max_length=100)

    test_domain.init(traverse=False)
    dao = test_domain.repository_for(Account)._dao

    dao.save(Account(email="a@example.com"))
    dao.save(Account(email="b@example.com"))

    # Bulk update onto a colliding value is accepted (no enforcement here).
    updated = dao._update_all(Q(("email", "b@example.com")), email="a@example.com")
    assert updated == 1
    assert dao.query.filter(email="a@example.com").all().total == 2
