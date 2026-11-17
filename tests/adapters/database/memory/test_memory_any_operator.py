from protean.core.aggregate import BaseAggregate
from protean.fields import List


class User(BaseAggregate):
    emails: List()


class Record(BaseAggregate):
    items: List(content_type=dict)


def test_for_any_lookup(test_domain):
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)

    user_repo.add(User(emails=["foo@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["baz@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["qux@example.com"]))

    # One result
    users = user_repo.query.filter(emails__any=["foo@example.com"]).all().items
    assert len(users) == 1

    # Scalar value to `any`
    users = user_repo.query.filter(emails__any="foo@example.com").all().items
    assert len(users) == 1

    # Multiple results
    users = user_repo.query.filter(emails__any=["bar@example.com"]).all().items
    assert len(users) == 2

    # Multiple input values
    users = (
        user_repo.query.filter(emails__any=["foo@example.com", "baz@example.com"])
        .all()
        .items
    )
    assert len(users) == 2

    # Single value in target list
    users = user_repo.query.filter(emails__any=["qux@example.com"]).all().items
    assert len(users) == 1


def test_for_overlap_lookup(test_domain):
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)

    user_repo.add(User(emails=["foo@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["baz@example.com", "bar@example.com"]))
    user_repo.add(User(emails=["qux@example.com"]))

    # Shares "bar" with the first two rows
    users = user_repo.query.filter(emails__overlap=["bar@example.com"]).all().items
    assert len(users) == 2

    # Shares an element with every row
    users = (
        user_repo.query.filter(
            emails__overlap=["foo@example.com", "baz@example.com", "qux@example.com"]
        )
        .all()
        .items
    )
    assert len(users) == 3

    # No shared element
    users = user_repo.query.filter(emails__overlap=["nope@example.com"]).all().items
    assert len(users) == 0


def test_array_lookups_handle_unhashable_elements(test_domain):
    # List elements can be dicts (unhashable); membership must compare by
    # equality, not hashing, so these lookups must not raise TypeError.
    test_domain.register(Record)

    record_repo = test_domain.repository_for(Record)
    record_repo.add(Record(items=[{"k": 1}, {"k": 2}]))
    record_repo.add(Record(items=[{"k": 3}]))

    matched = record_repo.query.filter(items__overlap=[{"k": 1}]).all().items
    assert len(matched) == 1

    matched = record_repo.query.filter(items__any=[{"k": 3}]).all().items
    assert len(matched) == 1

    matched = record_repo.query.filter(items__any=[{"k": 9}]).all().items
    assert len(matched) == 0


def test_empty_array_lookups_match_nothing(test_domain):
    # An empty target shares no element with any row, so `any`/`overlap`
    # against `[]` match nothing (match-none semantics).
    test_domain.register(User)

    user_repo = test_domain.repository_for(User)
    user_repo.add(User(emails=["foo@example.com"]))
    user_repo.add(User(emails=["bar@example.com"]))

    assert len(user_repo.query.filter(emails__any=[]).all().items) == 0
    assert len(user_repo.query.filter(emails__overlap=[]).all().items) == 0
