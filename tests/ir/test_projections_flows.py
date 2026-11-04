"""Tests for IRBuilder projections and flows extraction."""

import pytest

from protean import Domain, handle
from protean.fields.simple import Float, Identifier, Integer, String
from protean.ir.builder import IRBuilder


def build_projection_test_domain() -> Domain:
    """Build a domain with a projection, projector, query, and query handler."""
    from protean.utils.mixins import read

    domain = Domain(name="Reporting", root_path=".")

    @domain.event(part_of="Account")
    class AccountOpened:
        account_id = Identifier(required=True)
        holder_name = String(required=True)

    @domain.aggregate
    class Account:
        holder_name = String(max_length=100, required=True)
        balance = Float(default=0.0)

    @domain.projection
    class AccountSummary:
        account_id = Identifier(required=True, identifier=True)
        holder_name = String(max_length=100)
        transaction_count = Integer(default=0)

    @domain.projector(projector_for=AccountSummary, aggregates=[Account])
    class AccountSummaryProjector:
        @handle(AccountOpened)
        def on_account_opened(self, event):
            pass

    @domain.query(part_of=AccountSummary)
    class GetAccountSummary:
        account_id = Identifier(required=True)

    @domain.query_handler(part_of=AccountSummary)
    class AccountSummaryQueryHandler:
        @read(GetAccountSummary)
        def by_account(self, query):
            pass

    domain.init(traverse=False)
    return domain


def build_subscriber_test_domain() -> Domain:
    """Build a domain with a subscriber."""
    domain = Domain(name="Integrations", root_path=".")

    @domain.subscriber(broker="default", stream="external_events")
    class ExternalSubscriber:
        def __call__(self, payload):
            pass

    domain.init(traverse=False)
    return domain


@pytest.mark.no_test_domain
class TestProjectionExtraction:
    """Verify projection structure in IR."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = build_projection_test_domain()
        self.ir = IRBuilder(domain).build()

    def test_projection_structure(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        assert "projection" in proj_entry
        assert "projectors" in proj_entry
        assert "queries" in proj_entry
        assert "query_handlers" in proj_entry

    def test_projection_element_type(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        assert proj_entry["projection"]["element_type"] == "PROJECTION"

    def test_projection_identity_field(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        assert proj_entry["projection"]["identity_field"] == "account_id"

    def test_projection_fields(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        fields = proj_entry["projection"]["fields"]
        assert "account_id" in fields
        assert "holder_name" in fields
        assert "transaction_count" in fields

    def test_projection_options(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        opts = proj_entry["projection"]["options"]
        assert "provider" in opts
        assert "schema_name" in opts
        assert "limit" in opts

    @pytest.mark.parametrize(
        ("section", "element_type"),
        [
            ("projectors", "PROJECTOR"),
            ("queries", "QUERY"),
            ("query_handlers", "QUERY_HANDLER"),
        ],
    )
    def test_each_section_holds_one_element_of_its_type(self, section, element_type):
        proj_entry = next(iter(self.ir["projections"].values()))
        members = list(proj_entry[section].values())
        assert len(members) == 1
        assert members[0]["element_type"] == element_type

    def test_projector_for(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        projector = next(iter(proj_entry["projectors"].values()))
        proj_fqn = proj_entry["projection"]["fqn"]
        assert projector["projector_for"] == proj_fqn

    def test_projector_handlers(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        projector = next(iter(proj_entry["projectors"].values()))
        assert len(projector["handlers"]) >= 1

    def test_projector_aggregates(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        projector = next(iter(proj_entry["projectors"].values()))
        assert len(projector["aggregates"]) >= 1

    def test_query_type_no_version(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        query = next(iter(proj_entry["queries"].values()))
        # Queries don't have version suffix
        assert "__type__" in query
        assert not query["__type__"].endswith(".v1")

    @pytest.mark.parametrize("section", ["queries", "query_handlers"])
    def test_query_side_elements_are_part_of_the_projection(self, section):
        proj_entry = next(iter(self.ir["projections"].values()))
        element = next(iter(proj_entry[section].values()))
        assert element["part_of"] == proj_entry["projection"]["fqn"]

    def test_all_keys_sorted(self):
        proj_entry = next(iter(self.ir["projections"].values()))
        for section_name, section in proj_entry.items():
            if isinstance(section, dict) and "element_type" in section:
                keys = list(section.keys())
                assert keys == sorted(keys), f"Keys not sorted in {section_name}"


@pytest.mark.no_test_domain
class TestSubscriberExtraction:
    """Verify subscriber structure in IR flows."""

    @pytest.fixture(autouse=True)
    def setup(self):
        domain = build_subscriber_test_domain()
        self.ir = IRBuilder(domain).build()

    def test_subscriber_present(self):
        assert len(self.ir["flows"]["subscribers"]) == 1

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("element_type", "SUBSCRIBER"),
            ("broker", "default"),
            ("stream", "external_events"),
        ],
    )
    def test_subscriber_records_its_declaration(self, key, expected):
        sub = next(iter(self.ir["flows"]["subscribers"].values()))
        assert sub[key] == expected

    def test_subscriber_keys_sorted(self):
        sub = next(iter(self.ir["flows"]["subscribers"].values()))
        keys = list(sub.keys())
        assert keys == sorted(keys)


@pytest.mark.no_test_domain
class TestFlowsStructure:
    """Verify flows dict has all required subsections."""

    def test_flows_subsections(self):
        domain = Domain(name="Empty", root_path=".")
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        flows = ir["flows"]
        assert "domain_services" in flows
        assert "process_managers" in flows
        assert "subscribers" in flows
