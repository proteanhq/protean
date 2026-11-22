"""The BDD examples on ``docs/guides/testing/application-tests.md`` pass under pytest-bdd.

Each step file runs with the conftests above it: the root ``conftest.py`` that
initializes the ``myapp`` domain with sync processing, the shared
``the domain is initialized`` step with the marker registration for the
Gherkin tags, and the ordering steps. Every scenario in the feature files must
pass, and each tag selection the page lists must pick the tagged scenarios.
"""

import json
import re
import subprocess
import sys

import pytest

from tests.docs.support import (
    EXAMPLE_TESTS_TIMEOUT,
    example_env,
    outcome_counts,
    run_example_tests,
)

pytestmark = pytest.mark.no_test_domain


def test_the_registration_scenarios_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/registration/test_register_user.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 3}


def test_the_application_service_scenarios_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/registration/test_activate_user.py"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 2}


def test_the_ordering_scenarios_and_outline_pass():
    result = run_example_tests(
        "guides/testing/application-tests/bdd/ordering/test_place_order.py",
        args=["-W", "error::pytest.PytestUnknownMarkWarning"],
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": 6}


@pytest.mark.parametrize(
    "selection, expected",
    [
        pytest.param("ordering", 6, id="ordering"),
        pytest.param("smoke", 6, id="smoke"),
        pytest.param(
            "happy_path and not validation",
            ["test_placing_an_order_updates_inventory"],
            id="happy-path",
        ),
        pytest.param(
            "validation",
            ["test_cannot_order_more_than_available_stock"],
            id="validation",
        ),
    ],
)
def test_the_tag_selections_on_the_page_pick_the_tagged_scenarios(selection, expected):
    result = run_example_tests(
        "guides/testing/application-tests/bdd/ordering/test_place_order.py",
        args=["-m", selection, "--strict-markers", "-v"],
    )

    passed = re.findall(r"::(\S+) PASSED", result.stdout)
    assert result.returncode == 0, result.stdout + result.stderr
    if isinstance(expected, int):
        assert len(passed) == expected
    else:
        assert passed == expected


# Builds a ``PlaceOrder`` with a ``total`` and keeps the ``ValidationError``
# messages, or ``None`` when no error is raised. Then orders a book id that has
# no inventory row and keeps the messages the handler raises. Then orders 2
# copies of a book priced 15.50 and 3 copies of a book priced 4.25. It prints
# those messages, the number of stored orders and the stored order's total on a
# line that starts with "RESULT ". It runs in a child process so the ``myapp``
# domain is not registered in this interpreter.
_PLACE_ORDER_SCRIPT = """
import json

from myapp import domain
from protean.exceptions import ValidationError
from protean.integrations.pytest import DomainFixture

domain.config["event_processing"] = "sync"
domain.config["command_processing"] = "sync"
fixture = DomainFixture(domain)
fixture.setup()
with fixture.domain_context():
    from myapp.commands import PlaceOrder
    from myapp.models import Book, Customer, Inventory, Money, Order, OrderItemVO

    items = []
    for title, author, price, quantity in [
        ("Dune", "Frank Herbert", 15.50, 2),
        ("Emma", "Jane Austen", 4.25, 3),
    ]:
        book = Book(title=title, author=author, price=Money(amount=price))
        domain.repository_for(Book).add(book)
        domain.repository_for(Inventory).add(
            Inventory(book_id=book.id, title=title, quantity=5)
        )
        items.append(OrderItemVO(book_id=book.id, quantity=quantity))
    customer = Customer(name="Alice")
    domain.repository_for(Customer).add(customer)

    try:
        PlaceOrder(customer_id=customer.id, items=items, total=1.0)
        rejected = None
    except ValidationError as exc:
        rejected = exc.messages

    try:
        domain.process(
            PlaceOrder(
                customer_id=customer.id,
                items=[OrderItemVO(book_id="no-such-book", quantity=1)],
            )
        )
        unknown_book = None
    except ValidationError as exc:
        unknown_book = exc.messages

    domain.process(PlaceOrder(customer_id=customer.id, items=items))
    orders = domain.repository_for(Order).query.all().items
    print(
        "RESULT "
        + json.dumps(
            {
                "rejected": rejected,
                "unknown_book": unknown_book,
                "orders": len(orders),
                "total": orders[0].total if orders else None,
            }
        )
    )
fixture.teardown()
"""


def test_the_order_handler_computes_the_total_from_the_book_prices():
    result = subprocess.run(
        [sys.executable, "-c", _PLACE_ORDER_SCRIPT],
        capture_output=True,
        text=True,
        check=False,
        env=example_env(),
        timeout=EXAMPLE_TESTS_TIMEOUT,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
    assert len(lines) == 1, result.stdout + result.stderr
    outcome = json.loads(lines[0].removeprefix("RESULT "))
    assert outcome["rejected"] == {"total": ["Extra inputs are not permitted"]}
    assert outcome["unknown_book"] == {"items": ["Insufficient stock"]}
    assert outcome["orders"] == 1
    assert outcome["total"] == 43.75
