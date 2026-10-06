"""Run the projector assets' events through their projectors.

``test_examples.py`` only initializes each asset, and the snippet runner only
catches exceptions. A projector subscribed to the wrong stream category (a bare
``"user"`` where the category is ``<domain>::user``) initializes cleanly and
raises nothing: it just never receives an event. These tests persist the
aggregate that raises the source event, under synchronous event processing, and
assert the projection record appears. The event reaches the projector through
its stream subscription, so a wrong category leaves the record missing.

Each asset runs under its own ``run_name`` so the domains' registrations stay in
separate namespaces.
"""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain

# These build domains directly from package data; they never touch the autouse
# ``test_domain`` fixture.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
SKILLS_ROOT = PACK_ROOT / dx.SKILLS_DIR

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the projector assets are executed by path",
        allow_module_level=True,
    )


def _load(relative: str, run_name: str) -> tuple[dict[str, Any], Domain]:
    """Run one asset and return its namespace and its initialized domain."""
    namespace = runpy.run_path(str(SKILLS_ROOT / relative), run_name=run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    assert len(domains) == 1, f"{relative} must define exactly one Domain"
    domain = domains[0]
    assert domain.config["event_processing"] == "sync"
    domain.init(traverse=False)
    return namespace, domain


def test_single_aggregate_projector_creates_the_record():
    ns, domain = _load(
        "projector/assets/projector_single_aggregate.py", "projector_single_example"
    )
    Product, ProductInventory = ns["Product"], ns["ProductInventory"]

    with domain.domain_context():
        product = Product.create(name="Laptop", stock_quantity=50)
        domain.repository_for(Product).add(product)

        inventory = domain.repository_for(ProductInventory).get(product.id)
        assert inventory.name == "Laptop"
        assert inventory.stock_quantity == 50


def test_cross_aggregate_projector_creates_then_updates_the_record():
    ns, domain = _load(
        "projector/assets/projector_cross_aggregate.py", "projector_cross_example"
    )
    User, Transaction, Balances = ns["User"], ns["Transaction"], ns["Balances"]

    with domain.domain_context():
        user = User.register(email="alice@example.com", name="Alice")
        domain.repository_for(User).add(user)

        balance = domain.repository_for(Balances).get(user.id)
        assert balance.name == "Alice"
        assert balance.balance == 0

        txn = Transaction.transact(user_id=user.id, amount=100.0)
        domain.repository_for(Transaction).add(txn)

        balance = domain.repository_for(Balances).get(user.id)
        assert balance.balance == 100.0
