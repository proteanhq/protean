"""Diagnostics: TestSubscriberNoStreams."""

from protean import Domain
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    _findings,
)


class TestSubscriberNoStreams:
    """SUBSCRIBER_NO_STREAMS: a subscriber with no stream has nothing to
    consume. Keys off ``stream`` (not the removed ``stream_category``)."""

    def test_streamless_subscriber_flagged(self):
        domain = Domain(name="NoStreamSub", root_path=".")

        @domain.subscriber(broker="default", stream="payments")
        class PaymentSubscriber:
            def __call__(self, payload):
                pass

        domain.init(traverse=False)

        # The subscriber factory hard-requires a stream, so a streamless
        # subscriber cannot be registered. It can still appear in materialized
        # IR (loaded or hand-edited), which is what this info rule guards — null
        # the stream post-init to exercise that path.
        PaymentSubscriber.meta_.stream = None
        ir = IRBuilder(domain).build()

        findings = _findings(ir, "SUBSCRIBER_NO_STREAMS")
        assert len(findings) > 0
        finding = findings[0]
        assert "PaymentSubscriber" in finding["element"]
        assert finding["level"] == "info"

    def test_subscriber_with_stream_not_flagged(self):
        """A subscriber with a real ``stream`` produces zero findings — guards
        against a ``stream_category`` regression (the check reads ``stream``)."""
        domain = Domain(name="StreamSub", root_path=".")

        @domain.subscriber(broker="default", stream="payment_gateway")
        class PaymentSubscriber:
            def __call__(self, payload):
                pass

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _findings(ir, "SUBSCRIBER_NO_STREAMS") == []
