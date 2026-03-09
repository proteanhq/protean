"""Additional IR builder tests targeting uncovered lines."""

import pytest

from protean import Domain, handle
from protean.core.aggregate import apply
from protean.fields import ValueObject as VOField
from protean.fields.basic import ValueObjectList
from protean.fields.simple import Float, Identifier, Integer, String
from protean.ir.builder import IRBuilder


def _build_and_extract(domain: Domain) -> dict:
    return IRBuilder(domain).build()


# ------------------------------------------------------------------
# ValueObjectList field extraction (lines 110-114)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestValueObjectListExtraction:
    """Cover ValueObjectList field extraction in _extract_fields."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = Domain(name="VOListTest", root_path=".")

        @domain.value_object
        class Tag:
            label = String(max_length=50, required=True)

        @domain.aggregate
        class Article:
            title = String(max_length=200, required=True)
            tags = ValueObjectList(VOField(Tag))
            scores = ValueObjectList(content_type=float)

        domain.init(traverse=False)
        self.ir = _build_and_extract(domain)

        # Find Article cluster
        for fqn, cluster in self.ir["clusters"].items():
            if cluster["aggregate"]["name"] == "Article":
                self.article_fields = cluster["aggregate"]["fields"]
                break

    def test_vo_list_kind(self):
        assert self.article_fields["tags"]["kind"] == "value_object_list"

    def test_vo_list_target(self):
        assert "Tag" in self.article_fields["tags"]["target"]

    def test_scalar_vo_list_kind(self):
        """ValueObjectList with scalar content_type."""
        assert self.article_fields["scores"]["kind"] == "value_object_list"


# ------------------------------------------------------------------
# Required ValueObject field (line 107)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestRequiredVOField:
    """Cover required=True on ValueObject field."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = Domain(name="ReqVOTest", root_path=".")

        @domain.value_object
        class Email:
            address = String(max_length=255, required=True)

        @domain.aggregate
        class User:
            name = String(max_length=100, required=True)
            email = VOField(Email, required=True)

        domain.init(traverse=False)
        ir = _build_and_extract(domain)
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["name"] == "User":
                self.user_fields = cluster["aggregate"]["fields"]
                break

    def test_vo_field_required(self):
        assert self.user_fields["email"].get("required") is True

    def test_vo_field_kind(self):
        assert self.user_fields["email"]["kind"] == "value_object"


# ------------------------------------------------------------------
# Unique non-identifier field (line 178)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestUniqueField:
    """Cover unique=True on a non-identifier field."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = Domain(name="UniqueTest", root_path=".")

        @domain.aggregate
        class Product:
            name = String(max_length=100, required=True)
            sku = String(max_length=50, unique=True)

        domain.init(traverse=False)
        ir = _build_and_extract(domain)
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["name"] == "Product":
                self.product_fields = cluster["aggregate"]["fields"]
                break

    def test_unique_field_present(self):
        assert self.product_fields["sku"].get("unique") is True

    def test_identifier_field_no_unique(self):
        """Auto-generated id field is unique but should not duplicate."""
        id_field = self.product_fields.get("id", {})
        assert id_field.get("unique") is not True


# ------------------------------------------------------------------
# max_value on field (line 188)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestMaxValueField:
    """Cover max_value extraction."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = Domain(name="MaxValTest", root_path=".")

        @domain.aggregate
        class Rating:
            score = Integer(min_value=0, max_value=100)

        domain.init(traverse=False)
        ir = _build_and_extract(domain)
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["name"] == "Rating":
                self.rating_fields = cluster["aggregate"]["fields"]
                break

    def test_max_value_present(self):
        assert self.rating_fields["score"].get("max_value") == 100

    def test_min_value_present(self):
        assert self.rating_fields["score"].get("min_value") == 0


# ------------------------------------------------------------------
# PM correlate as string (line 805-806)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestPMCorrelateString:
    """Cover PM correlate as a simple string."""

    def test_correlate_string(self):
        domain = Domain(name="PMStr", root_path=".")

        @domain.event(part_of="Order")
        class OrderCreated:
            order_id = Identifier(required=True)

        @domain.aggregate
        class Order:
            total = Float(default=0.0)

        @domain.process_manager(stream_categories=["order"])
        class SimpleFlow:
            order_id = Identifier()

            @handle(OrderCreated, start=True, correlate="order_id")
            def on_created(self, event):
                pass

        domain.init(traverse=False)
        ir = _build_and_extract(domain)
        pm = list(ir["flows"]["process_managers"].values())[0]
        # Find handler with correlate
        for handler_info in pm["handlers"].values():
            if "correlate" in handler_info:
                assert handler_info["correlate"] == "order_id"
                break


# ------------------------------------------------------------------
# Auto-generated event skip in UNHANDLED_EVENT diagnostic (line 1138)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestAutoGeneratedEventSkipInDiagnostics:
    """Verify auto-generated events (PM transitions) are excluded from
    UNHANDLED_EVENT diagnostics."""

    def test_pm_transition_event_not_flagged(self):
        domain = Domain(name="PMDiag", root_path=".")

        @domain.event(part_of="Order")
        class OrderPlaced:
            order_id = Identifier(required=True)

        @domain.aggregate
        class Order:
            total = Float(default=0.0)

        @domain.event_handler(part_of=Order)
        class OrderHandler:
            @handle(OrderPlaced)
            def on_placed(self, event):
                pass

        @domain.process_manager(stream_categories=["order"])
        class OrderFlow:
            order_id = Identifier()
            status = String(default="new")

            @handle(OrderPlaced, start=True, correlate="order_id")
            def on_placed(self, event):
                self.status = "placed"
                self.mark_as_complete()

        domain.init(traverse=False)
        ir = _build_and_extract(domain)

        # The PM auto-generates a transition event — it should NOT be flagged
        unhandled = [d for d in ir["diagnostics"] if d["code"] == "UNHANDLED_EVENT"]
        # Only user-defined unhandled events should appear, not PM transitions
        for diag in unhandled:
            assert "Transition" not in diag["element"]


# ------------------------------------------------------------------
# Auto-generated event skip in ES_EVENT_MISSING_APPLY (line 1195)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestAutoGeneratedEventSkipInEsApply:
    """Verify auto-generated events are excluded from ES_EVENT_MISSING_APPLY."""

    def test_fact_event_not_flagged_in_es(self):
        """ES aggregate with fact_events: auto-generated fact event should
        not require @apply handler."""
        domain = Domain(name="ESFact", root_path=".")

        @domain.event(part_of="Account")
        class AccountOpened:
            holder = String(required=True)

        @domain.aggregate(is_event_sourced=True, fact_events=True)
        class Account:
            holder = String(max_length=100, required=True)

            @apply
            def opened(self, event: AccountOpened) -> None:
                self.holder = event.holder

        domain.init(traverse=False)
        ir = _build_and_extract(domain)
        missing = [
            d for d in ir["diagnostics"] if d["code"] == "ES_EVENT_MISSING_APPLY"
        ]
        # The auto-generated fact event should not be flagged
        assert len(missing) == 0


# ------------------------------------------------------------------
# VO with explicit part_of (lines 942-944)
# ------------------------------------------------------------------


@pytest.mark.no_test_domain
class TestVOExplicitPartOf:
    """Cover VO with explicit part_of in _map_vos_to_aggregates."""

    def test_vo_with_explicit_part_of(self):
        domain = Domain(name="VOPart", root_path=".")

        @domain.aggregate
        class Customer:
            name = String(max_length=100, required=True)

        @domain.value_object(part_of=Customer)
        class PhoneNumber:
            number = String(max_length=20, required=True)
            country_code = String(max_length=5, default="+1")

        domain.init(traverse=False)
        ir = _build_and_extract(domain)

        # PhoneNumber should appear in Customer's cluster
        for cluster in ir["clusters"].values():
            if cluster["aggregate"]["name"] == "Customer":
                assert any("PhoneNumber" in fqn for fqn in cluster["value_objects"])
                break
