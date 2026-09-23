"""The extract-bounded-context before/after assets: the diagnostic they teach.

``test_examples.py`` only inits each asset; it does not run ``check``. This
harness does: it builds each asset's IR, the way ``check`` does, and asserts the
extraction actually clears the smell it targets.

- The before asset is one ``Domain`` whose two clusters (``Order`` in sales,
  ``Shipment`` in fulfilment) reference each other, so ``check`` reports
  ``CIRCULAR_CLUSTER_DEPENDENCY`` on both. A cross-cluster ``Reference`` also
  trips ``CROSS_AGGREGATE_REFERENCE``; that is a co-smell the skill names, so the
  before asserts only the targeted code, not the absence of the others.
- The after asset splits the two into separate ``Domain`` objects that talk by a
  published event across the seam. Neither holds a ``Reference`` into the other,
  so ``check`` reports neither ``CIRCULAR_CLUSTER_DEPENDENCY`` nor
  ``CROSS_AGGREGATE_REFERENCE`` on either domain. A third test runs the after
  flow end to end and asserts a shipment is created from the sales event, so the
  subscriber and the event wiring the skill teaches are actually exercised.

Each asset is executed under its own ``run_name`` so the two runs' element
registrations land in separate namespaces and cannot collide (both assets define
same-named events and aggregates). The runner mirrors ``test_examples.py`` and
``test_saga_flow_example.py``.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import pytest

from protean import dx
from protean.domain import Domain
from protean.ir.builder import IRBuilder
from protean.utils.eventing import Message

# These build domains directly from package data; they never touch the autouse
# ``test_domain`` fixture, so skip it and its initialization cost.
pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS_DIR = PACK_ROOT / dx.SKILLS_DIR / "extract-bounded-context" / "assets"

CIRCULAR = "CIRCULAR_CLUSTER_DEPENDENCY"
CROSS_REFERENCE = "CROSS_AGGREGATE_REFERENCE"

# The runner executes an asset by path, so it needs the pack unpacked on disk.
# The accessor does not promise a filesystem root (a zip install would not have
# one); CI installs unzipped, so this skips cleanly only in the zip case.
if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the extract-bounded-context assets are "
        "executed by path",
        allow_module_level=True,
    )


def _run_asset(asset_name: str, run_name: str) -> dict:
    """Run one asset and return its module namespace."""
    return runpy.run_path(str(ASSETS_DIR / asset_name), run_name=run_name)


def _domains(asset_name: str, run_name: str) -> list[Domain]:
    """Run one asset and return the initialized domains it defines, in order."""
    namespace = _run_asset(asset_name, run_name)
    domains = [value for value in namespace.values() if isinstance(value, Domain)]
    for domain in domains:
        domain.init(traverse=False)
    return domains


def _findings(ir: dict, code: str) -> list[dict]:
    return [d for d in ir["diagnostics"] if d["code"] == code]


def test_before_asset_reports_circular_cluster_dependency():
    domains = _domains("extract_bounded_context_before.py", "_ebc_before_")
    assert len(domains) == 1, "the before asset is one Domain holding both contexts"
    ir = IRBuilder(domains[0]).build()

    findings = _findings(ir, CIRCULAR)
    elements = sorted(d["element"] for d in findings)
    # One diagnostic per participating cluster, both pinned to the run_name-
    # prefixed FQNs so a cross-contaminated after cluster cannot satisfy this.
    assert elements == ["_ebc_before_.Order", "_ebc_before_.Shipment"]
    for finding in findings:
        assert finding["level"] == "warning"


def test_after_asset_clears_the_targeted_codes_on_both_domains():
    domains = _domains("extract_bounded_context_after.py", "_ebc_after_")
    # Two separate contexts now: the sales domain and the fulfilment domain.
    assert len(domains) == 2, "the after asset splits the context into two Domains"

    for domain in domains:
        ir = IRBuilder(domain).build()
        assert _findings(ir, CIRCULAR) == [], (
            f"{domain.name} must not report {CIRCULAR}; the extraction removed the "
            "cross-context references that formed the cycle"
        )
        assert _findings(ir, CROSS_REFERENCE) == [], (
            f"{domain.name} must not report {CROSS_REFERENCE}; the seam now crosses "
            "by identity (order_id), with no Reference into the other context"
        )


def test_after_flow_creates_a_shipment_from_the_sales_event():
    # The IR tests above show the after clears the codes, but each after domain
    # has one aggregate, so neither code can fire and those assertions cannot go
    # red on a broken extraction. This runs the flow the skill teaches so the
    # subscriber and event wiring are actually exercised: place an order in
    # sales, carry the recorded OrderPlaced fact across the seam through the
    # asset's own relay, and assert fulfilment opens the matching shipment.
    #
    # The relay is the asset's `relay_last_order_event`, so this exercises the
    # delivery contract the skill teaches rather than one the test invents: the
    # stream is the sales aggregate's `stream_category` and the payload is the
    # `{"data", "metadata"}` envelope `Message.to_external_dict()` produces,
    # which is what `OutboxProcessor` publishes in a deployed system.
    namespace = _run_asset("extract_bounded_context_after.py", "_ebc_flow_")
    sales = namespace["sales"]
    fulfilment = namespace["fulfilment"]
    Order = namespace["Order"]
    PlaceOrder = namespace["PlaceOrder"]
    Shipment = namespace["Shipment"]
    OrderPlaced = namespace["OrderPlaced"]
    relay_last_order_event = namespace["relay_last_order_event"]
    sales.init(traverse=False)
    fulfilment.init(traverse=False)

    assert sales.has_outbox, (
        "the sales domain must have the outbox on, or a deployed domain would "
        "dispatch nothing and the subscriber would never hear the event"
    )

    # Broker names are local to a Domain, so both sides must declare the broker
    # the event crosses on. If only sales had "events", a deployed sales domain
    # would dispatch there while fulfilment listened on its own "default", and
    # the two would never meet.
    assert "events" in sales.brokers
    assert "events" in fulfilment.brokers, (
        "fulfilment must declare the shared 'events' broker; a Domain does not "
        "inherit another Domain's broker registry"
    )

    # The consumer names the message type as a string rather than importing the
    # producer's class. Pin that string to what sales actually emits, so the
    # decoupling cannot drift into a silently wrong contract.
    assert namespace["SALES_ORDER_PLACED"] == OrderPlaced.__type__

    with sales.domain_context():
        sales.process(PlaceOrder(customer_id="CUST-1", address="1 Market St"))
        fact = sales.event_store.store.read(Order.meta_.stream_category)[-1]

    assert fact.data["customer_id"] == "CUST-1", "sales must record OrderPlaced"
    order_id = fact.data["order_id"]

    # Pin the contract the subscriber is written against: the outbox routes by
    # this category, and delivers this envelope.
    external = fact.to_external_dict()
    assert fact.metadata.domain.stream_category == "sales::order"
    assert set(external) == {"data", "metadata"}
    assert external["data"]["order_id"] == order_id

    # Prove the producer side too, so this does not rest on `has_outbox` alone:
    # the published event must actually reach an *external* outbox row, and that
    # row must carry the category the subscriber subscribes to and the same
    # envelope the relay publishes. `_outbox_repos` is private, but it is the
    # only way to see the rows without running the server, and the asset itself
    # does not use it.
    #
    # Filter on `target_broker`. Every event gets an internal row targeting
    # "default" whether or not it is published, so matching on type alone would
    # pass even with nothing bound for external dispatch. "events" is the broker
    # named in `outbox.external_brokers`, so a row targeting it is the external
    # publication.
    with sales.domain_context():
        rows = sales._outbox_repos["default"]._dao.query.all().items
    published = [
        row
        for row in rows
        if row.type == OrderPlaced.__type__ and row.target_broker == "events"
    ]
    assert published, (
        "the published OrderPlaced must reach an outbox row targeting the "
        "external 'events' broker; without one a deployed OutboxProcessor has "
        "nothing to dispatch to fulfilment"
    )
    row = published[-1]
    assert row.metadata_.domain.stream_category == "sales::order"
    assert Message(data=row.data, metadata=row.metadata_).to_external_dict() == external

    relay_last_order_event()

    with fulfilment.domain_context():
        shipments = fulfilment.repository_for(Shipment).query.all()

    assert shipments.total == 1, (
        "fulfilment must open exactly one shipment from the sales event; the "
        "subscriber translates OrderPlaced into a CreateShipment command"
    )
    shipment = shipments.items[0]
    assert shipment.order_id == order_id, "the shipment holds the order by identity"
    assert shipment.address == "1 Market St"
    assert shipment.status == "pending"
