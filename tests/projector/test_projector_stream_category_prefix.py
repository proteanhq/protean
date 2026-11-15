"""A projector's ``stream_categories`` name categories inside its own domain."""

from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.fields import Identifier, String
from protean.server import Engine


class Return(BaseAggregate):
    reason = String()


class ReturnRequested(BaseEvent):
    return_id = Identifier(required=True)


class ReturnReport(BaseProjection):
    return_id = Identifier(identifier=True)


received: list[str] = []


class ReturnReportProjector(BaseProjector):
    @on(ReturnRequested)
    def on_requested(self, event: ReturnRequested) -> None:
        received.append(event.return_id)


def _register(test_domain, **opts):
    test_domain.register(ReturnReport)
    test_domain.register(ReturnReportProjector, projector_for=ReturnReport, **opts)


def test_a_bare_category_gets_the_domain_prefix(test_domain):
    _register(test_domain, stream_categories=["all_orders", "$all"])

    assert ReturnReportProjector.meta_.stream_categories == [
        "test::all_orders",
        "$all",
    ]


def test_a_qualified_category_stays_as_written(test_domain):
    _register(test_domain, stream_categories=["billing::invoice"])

    assert ReturnReportProjector.meta_.stream_categories == ["billing::invoice"]


def test_a_category_derived_from_aggregates_is_not_prefixed_twice(test_domain):
    test_domain.register(Return)
    _register(test_domain, aggregates=[Return])

    assert ReturnReportProjector.meta_.stream_categories == ["test::return"]


def test_a_bare_category_reads_the_aggregate_with_that_category(test_domain):
    received.clear()
    test_domain.config["event_processing"] = "async"
    test_domain.register(Return, stream_category="all_orders")
    test_domain.register(ReturnRequested, part_of=Return)
    _register(test_domain, stream_categories=["all_orders"])
    test_domain.init(traverse=False)

    returned = Return(reason="damaged")
    returned.raise_(ReturnRequested(return_id=returned.id))
    test_domain.repository_for(Return).add(returned)

    Engine(domain=test_domain, test_mode=True).run()

    assert received == [returned.id]
