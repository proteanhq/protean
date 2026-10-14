# --8<-- [start:imports]
import re

import pytest
from ticketing import domain

from protean.integrations.pytest import (
    assert_no_overfetch,
    assert_no_subquery_wrap,
    assert_query_count,
    capture_queries,
)

# --8<-- [end:imports]


# --8<-- [start:query_count]
@pytest.mark.database
def test_poll_issues_a_single_query(ticket_repo, seeded_tickets):
    with assert_query_count(1):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:query_count]


# --8<-- [start:subquery_wrap]
@pytest.mark.database
def test_count_uses_a_flat_count(ticket_repo):
    with assert_no_subquery_wrap():
        ticket_repo.count_pending()


@pytest.mark.database
def test_a_wrapped_count_fails(ticket_repo):
    engine = domain.providers["default"]._engine
    wrapped = "SELECT count(*) FROM (SELECT id FROM ticket LIMIT 5) AS anon_1"

    with pytest.raises(AssertionError):
        with assert_no_subquery_wrap():
            with engine.connect() as connection:
                connection.exec_driver_sql(wrapped)


# --8<-- [end:subquery_wrap]


# --8<-- [start:overfetch]
@pytest.mark.database
def test_poll_does_not_overfetch(ticket_repo, seeded_tickets):
    with assert_no_overfetch(expected_returned=10):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:overfetch]


# --8<-- [start:capture_queries]
@pytest.mark.database
def test_parent_inserted_before_children(order_repo, order):
    with capture_queries() as captured:
        order_repo.add(order)

    tables = [
        re.search(r'INSERT INTO "?(\w+)', statement, re.IGNORECASE).group(1).lower()
        for statement, _params in captured
        if statement.lstrip().upper().startswith("INSERT")
    ]
    assert tables, "no INSERTs captured; the hook did not fire"
    assert tables.index("order") < tables.index("order_item")


# --8<-- [end:capture_queries]


# --8<-- [start:explicit_engine]
@pytest.mark.database
def test_poll_on_an_explicit_engine(ticket_repo):
    my_engine = domain.providers["default"]._engine

    with assert_query_count(1, engine=my_engine):
        ticket_repo.find_pending(limit=10)


# --8<-- [end:explicit_engine]
