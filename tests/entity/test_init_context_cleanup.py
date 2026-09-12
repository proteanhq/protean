"""A failed construction must not leak the thread-local init-context stack.

``BaseEntity.__init__`` pushes an entry onto ``_init_context.stack`` before
Pydantic validation and relies on ``model_post_init`` to pop it. Pydantic does
not call ``model_post_init`` when validation fails, so the failure path in
``__init__`` has to pop the entry itself. Without that, a caller catching the
``ValidationError`` in a loop (for example the event store discarding stale
snapshots) leaks one entry per attempt.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import _init_context
from protean.exceptions import ValidationError
from protean.fields import Identifier, String


class Widget(BaseAggregate):
    widget_id: Identifier(identifier=True)
    name: String(required=True, max_length=15)


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Widget)
    test_domain.init(traverse=False)


def test_failed_construction_does_not_leak_init_context(test_domain):
    before = len(getattr(_init_context, "stack", []))

    for _ in range(3):
        with pytest.raises(ValidationError):
            Widget(widget_id="w1", name="ok", unknown_field="x")

    after = len(getattr(_init_context, "stack", []))
    assert after == before
