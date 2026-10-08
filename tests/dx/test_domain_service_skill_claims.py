"""The domain service skills state the invariant rules the framework follows.

The domain-service and add-domain-service-flow skills tell a reader how
invariants wrap a domain service's methods. These tests run each rule against
the framework, and check that no page in the pack or the docs claims a public
helper raises ``RecursionError``. A public method calling another public method
runs the invariants again against the state reached so far, which raises
``ValidationError`` when that state breaks one; only an invariant calling a
public helper recurses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protean import Domain, dx, invariant
from protean.exceptions import ValidationError
from protean.fields import Integer

pytestmark = pytest.mark.no_test_domain

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_ROOT = Path(str(dx.pack_files()))

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the page scan reads it by path",
        allow_module_level=True,
    )


def _domain_with_service():
    domain = Domain(name="DomainServiceClaims")
    calls: list[str] = []

    @domain.aggregate
    class Order:
        total = Integer(default=0)

    @domain.aggregate
    class Inventory:
        quantity = Integer(default=0)

    @domain.domain_service(part_of=[Order, Inventory])
    class Fulfillment:
        # No super().__init__() call: the invariants are wired at registration.
        def __init__(self, order, inventory):
            self.order = order
            self.inventory = inventory

        @invariant.pre
        def in_stock(self):
            calls.append("in_stock")
            if self.inventory.quantity < 1:
                raise ValidationError({"_service": ["Out of stock"]})

        def confirm(self):
            return self.helper()

        def reserve_all(self):
            self.inventory.quantity = 0
            return self.helper()

        def helper(self):
            return "confirmed"

        def _private_helper(self):
            return "private"

    domain.init(traverse=False)
    return domain, Order, Inventory, Fulfillment, calls


def test_pre_invariant_runs_without_super_init():
    domain, Order, Inventory, Fulfillment, _ = _domain_with_service()

    with domain.domain_context():
        with pytest.raises(ValidationError) as exc_info:
            Fulfillment(Order(), Inventory(quantity=0)).confirm()

    assert exc_info.value.messages == {"_service": ["Out of stock"]}


def test_public_helper_runs_the_invariants_again_without_failing():
    domain, Order, Inventory, Fulfillment, calls = _domain_with_service()

    with domain.domain_context():
        result = Fulfillment(Order(), Inventory(quantity=5)).confirm()

    assert result == "confirmed"
    # Once around confirm(), once around the public helper it calls
    assert calls == ["in_stock", "in_stock"]


def test_public_helper_checks_the_state_the_outer_method_reached():
    domain, Order, Inventory, Fulfillment, calls = _domain_with_service()

    with domain.domain_context():
        with pytest.raises(ValidationError) as exc_info:
            Fulfillment(Order(), Inventory(quantity=5)).reserve_all()

    assert exc_info.value.messages == {"_service": ["Out of stock"]}
    # Passed around reserve_all(), failed around the helper after the change
    assert calls == ["in_stock", "in_stock"]


def test_underscore_helper_is_not_wrapped():
    domain, Order, Inventory, Fulfillment, calls = _domain_with_service()

    with domain.domain_context():
        result = Fulfillment(Order(), Inventory(quantity=0))._private_helper()

    assert result == "private"
    assert calls == []


def test_invariant_calling_a_public_helper_stops_at_the_recursion_limit():
    domain = Domain(name="DomainServiceRecursion")

    @domain.aggregate
    class Order:
        total = Integer(default=0)

    @domain.aggregate
    class Inventory:
        quantity = Integer(default=0)

    @domain.domain_service(part_of=[Order, Inventory])
    class Fulfillment:
        def __init__(self, order, inventory):
            self.order = order
            self.inventory = inventory

        @invariant.pre
        def in_stock(self):
            if self.stock() < 1:
                raise ValidationError({"_service": ["Out of stock"]})

        def stock(self):
            return self.inventory.quantity

    domain.init(traverse=False)

    with domain.domain_context():
        with pytest.raises(RecursionError):
            Fulfillment(Order(), Inventory(quantity=5)).stock()


def test_no_page_claims_a_recursion_error():
    pages = sorted(PACK_ROOT.rglob("*.md")) + sorted((REPO_ROOT / "docs").rglob("*.md"))
    assert pages, "found no Markdown pages to scan"

    offenders = [
        str(page.relative_to(REPO_ROOT))
        for page in pages
        if "RecursionError" in page.read_text(encoding="utf-8")
    ]

    assert offenders == []
