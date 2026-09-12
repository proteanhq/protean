"""A failed construction must not leak the thread-local init-context stack.

``BaseEntity.__init__`` pushes an entry onto ``_init_context.stack`` before
Pydantic validation and relies on ``model_post_init`` to pop it. When
construction raises before ``model_post_init`` runs (Pydantic field validation
fails, or an abstract class is rejected), the entry is left behind, so
``__init__`` balances it in a ``finally``. Without that, a caller catching the
error in a loop (for example the event store discarding stale snapshots) leaks
one entry per attempt.
"""

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.entity import _init_context
from protean.exceptions import NotSupportedError, ValidationError
from protean.fields import Identifier, String


class Widget(BaseAggregate):
    widget_id: Identifier(identifier=True)
    name: String(required=True, max_length=15)


class AbstractWidget(BaseAggregate):
    widget_id: Identifier(identifier=True)
    name: String()


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Widget)
    test_domain.register(AbstractWidget, abstract=True)
    test_domain.init(traverse=False)


def test_field_validation_failure_does_not_leak_init_context(test_domain):
    """Pydantic rejects the extra field before ``model_post_init`` runs."""
    before = len(getattr(_init_context, "stack", []))

    for _ in range(3):
        with pytest.raises(ValidationError):
            Widget(widget_id="w1", name="ok", unknown_field="x")

    after = len(getattr(_init_context, "stack", []))
    assert after == before


def test_abstract_construction_does_not_leak_init_context(test_domain):
    """An abstract class raises ``NotSupportedError`` from ``model_post_init``
    before it pops the entry. That error is not a Pydantic ``ValidationError``,
    so only the ``finally`` cleanup balances the stack here."""
    before = len(getattr(_init_context, "stack", []))

    for _ in range(3):
        with pytest.raises(NotSupportedError):
            AbstractWidget(widget_id="w1", name="x")

    after = len(getattr(_init_context, "stack", []))
    assert after == before
