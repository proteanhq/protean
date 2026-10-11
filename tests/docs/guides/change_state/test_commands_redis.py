"""Check the Redis deduplication example on docs/guides/change-state/commands.md.

Submission-level deduplication needs Redis, so these tests run in the FULL leg.
The example's ``place_order_once`` sends every order with the key
``req-abc-123``.
"""

import pytest

from tests.docs.support import load_example
from tests.shared import REDIS_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.redis]


@pytest.fixture
def example():
    module = load_example("guides/change-state/commands/001.py")
    module.domain.config["idempotency"]["redis_url"] = f"{REDIS_URI}/9"
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        module.domain.idempotency_store.flush()
        yield module
        module.domain.idempotency_store.flush()


def saved_ids(module):
    return [
        order.id
        for order in module.domain.repository_for(module.Order).query.all().items
    ]


def test_a_repeated_key_hands_back_the_first_result(example):
    assert example.place_order_once("ord-1", ["book"]) is None

    # The handler returned the key the first time, and the duplicate gets that
    # result back through DuplicateCommandError.
    assert example.place_order_once("ord-2", ["pen"]) == "req-abc-123"

    assert saved_ids(example) == ["ord-1"]


def test_without_raise_on_duplicate_the_cached_result_is_returned(example):
    assert example.place_order("ord-1", ["book"]) == "req-abc-123"
    assert example.place_order("ord-2", ["pen"]) == "req-abc-123"

    assert saved_ids(example) == ["ord-1"]
