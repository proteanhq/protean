"""Diagnostics: TestUnindexedFilterPath.

UNINDEXED_FILTER_PATH joins the declared-index half of the IR with the
filter-path half from the behavioral substrate: it flags an aggregate field a
repository query filters on that no declared index covers. The corpus lives in
:mod:`tests.ir.support.unindexed_filter_domain.catalog` because the rule reads
method bodies through the substrate, which needs real, importable source.
"""

import re
from pathlib import Path

import pytest

from protean import Domain
from protean.core.index import Index
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.support import unindexed_filter_domain as _pkg
from tests.ir.support.unindexed_filter_domain import catalog

CORPUS_ROOT = str(Path(_pkg.__file__).parent)

# The message names the call-site as ``filtered by `<fqn>.<method>, line N```.
_CALLSITE_RE = re.compile(r"filtered by `(?P<fqn>[\w.]+)\.(?P<method>\w+), line (\d+)`")


def _flagged(ir: dict) -> list[dict]:
    """Diagnostics with code ``UNINDEXED_FILTER_PATH``."""
    return [d for d in ir["diagnostics"] if d["code"] == "UNINDEXED_FILTER_PATH"]


def _method_of(finding: dict) -> str:
    """The call-site method name a finding's message reports."""
    match = _CALLSITE_RE.search(finding["message"])
    assert match, f"message names no call-site: {finding['message']}"
    return match.group("method")


def _flagged_methods(ir: dict) -> list[str]:
    return [_method_of(d) for d in _flagged(ir)]


@pytest.fixture(scope="module")
def flagged_ir() -> dict:
    """The shared corpus registered as one domain, built once.

    ``Order`` carries a single-column ``Index("status")`` and a composite
    ``Index("channel", "region")``; ``Account`` carries no index but a ``unique``
    email. The repositories and the application service filter across the whole
    field surface, so a single build exercises every covered/flagged branch.
    """
    domain = Domain(name="UnindexedFilterPath", root_path=CORPUS_ROOT)
    domain.register(
        catalog.Order, indexes=[Index("status"), Index("channel", "region")]
    )
    domain.register(catalog.Account)
    domain.register(catalog.OrderRepository, part_of=catalog.Order)
    domain.register(catalog.AccountRepository, part_of=catalog.Account)
    domain.register(catalog.OrderService, part_of=catalog.Order)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


class TestUnindexedFilterPath:
    """The rule flags a filtered field no declared index covers, and leaves the
    covered and unresolvable ones alone."""

    def test_the_rule_is_active(self, flagged_ir):
        """A guard so every absence assertion below is non-vacuous: the corpus
        genuinely produces findings, so a ``method not in ...`` check is a real
        exclusion, not an empty-list pass."""
        assert len(_flagged(flagged_ir)) > 0

    # ── Covered fields — no finding ──────────────────────────────────────

    def test_indexed_field_not_flagged(self, flagged_ir):
        """A filter on the leading (only) column of ``Index("status")`` is
        covered."""
        assert "filter_indexed" not in _flagged_methods(flagged_ir)

    def test_leading_composite_column_not_flagged(self, flagged_ir):
        """The leading column of a composite index is covered."""
        assert "filter_leading_composite" not in _flagged_methods(flagged_ir)

    def test_identity_get_not_flagged(self, flagged_ir):
        """A ``get`` on the identifier field is covered — every backend indexes
        the primary key."""
        assert "get_identity" not in _flagged_methods(flagged_ir)

    def test_unique_field_not_flagged(self, flagged_ir):
        """A filter on a ``unique`` field is covered by the unique constraint."""
        assert "filter_unique" not in _flagged_methods(flagged_ir)

    # ── Flagged fields — one finding per uncovered call-site ─────────────

    def test_plain_field_flagged(self, flagged_ir):
        """A repository filter on a non-indexed field is flagged, attributed to
        the aggregate FQN with the field name."""
        findings = [d for d in _flagged(flagged_ir) if _method_of(d) == "filter_plain"]
        # ``filter_plain`` exists on both repositories (Order.name, Account.city);
        # pin the Order one.
        order = [d for d in findings if d["element"] == fqn(catalog.Order)]
        assert len(order) == 1, order
        finding = order[0]
        assert finding["field"] == "name"
        assert finding["category"] == "persistence"
        assert finding["level"] == "warning"
        assert "Order" in finding["message"]
        assert "name" in finding["message"]

    def test_nonleading_composite_column_flagged(self, flagged_ir):
        """A filter on a non-leading column of a composite index alone is not
        served by that index, so it is flagged."""
        findings = [
            d
            for d in _flagged(flagged_ir)
            if _method_of(d) == "filter_nonleading_composite"
        ]
        assert len(findings) == 1, findings
        assert findings[0]["field"] == "region"
        assert findings[0]["element"] == fqn(catalog.Order)

    def test_get_on_plain_field_flagged(self, flagged_ir):
        """The rule reads the whole query surface, not only ``filter``: a
        ``get`` on a non-identity field is flagged too."""
        findings = [d for d in _flagged(flagged_ir) if _method_of(d) == "get_plain"]
        assert len(findings) == 1, findings
        assert findings[0]["field"] == "name"

    def test_second_aggregate_attributed(self, flagged_ir):
        """A finding on a different aggregate is attributed to its own FQN, not
        leaked onto the first — the join is per-aggregate."""
        account = [
            d for d in _flagged(flagged_ir) if d["element"] == fqn(catalog.Account)
        ]
        assert len(account) == 1, account
        assert account[0]["field"] == "city"
        assert _method_of(account[0]) == "filter_plain"

    def test_application_service_filter_path_found(self, flagged_ir):
        """Whole-package scope: a filter path in an application service that
        references the aggregate class by name joins to that aggregate."""
        findings = [
            d for d in _flagged(flagged_ir) if _method_of(d) == "by_plain_field"
        ]
        assert len(findings) == 1, findings
        assert findings[0]["element"] == fqn(catalog.Order)
        assert findings[0]["field"] == "name"

    def test_one_finding_per_call_site(self, flagged_ir):
        """Two ``filter`` call-sites on the same field yield two findings, not
        one deduped — parity with the sibling per-occurrence persistence rule."""
        findings = [d for d in _flagged(flagged_ir) if _method_of(d) == "filter_twice"]
        assert len(findings) == 2, findings
        assert all(d["field"] == "name" for d in findings)

    # ── Unresolvable / dynamic paths — skipped, no false positive ────────

    def test_dynamic_filter_not_flagged(self, flagged_ir):
        """``filter(**kwargs)`` names no field, so it self-skips."""
        assert "filter_dynamic" not in _flagged_methods(flagged_ir)

    def test_variable_receiver_not_flagged(self, flagged_ir):
        """A ``.filter`` on a plain parameter (receiver role UNKNOWN) is not a
        repository query, so it is skipped rather than guessed."""
        assert "filter_variable" not in _flagged_methods(flagged_ir)

    def test_application_service_variable_receiver_not_flagged(self, flagged_ir):
        """The application-service path is subject to the same skip: a filter on
        an unresolvable receiver is not joined."""
        assert "by_variable" not in _flagged_methods(flagged_ir)

    # ── Cross-cutting shape ──────────────────────────────────────────────

    def test_finding_reports_the_call_site_location(self, flagged_ir):
        """The message names the enclosing element FQN, the method, and the
        source line — stable across machines (no absolute path) so it does not
        pollute the content-checksummed IR — so a reviewer can find the query.

        The app-service finding pins that the *source* element (where the query
        is written) is named distinctly from the ``element`` FQN (the aggregate
        the finding is attributed to)."""
        finding = next(
            d for d in _flagged(flagged_ir) if _method_of(d) == "by_plain_field"
        )
        match = _CALLSITE_RE.search(finding["message"])
        assert match, finding["message"]
        assert match.group("fqn") == fqn(catalog.OrderService)
        assert match.group("method") == "by_plain_field"
        assert int(match.group(3)) > 0
        # The query lives on the application service, not on the aggregate the
        # finding is attributed to.
        assert finding["element"] == fqn(catalog.Order)
        assert "/" not in finding["message"], "no absolute path in the message"

    def test_finding_carries_the_enriched_schema(self, flagged_ir):
        """The #774 schema surface: category, a non-empty rule, and a
        field-specific suggestion."""
        finding = next(
            d
            for d in _flagged(flagged_ir)
            if _method_of(d) == "filter_plain" and d["element"] == fqn(catalog.Order)
        )
        assert finding["category"] == "persistence"
        assert finding["rule"]["rationale"]
        assert finding["rule"]["fix"]
        assert "name" in finding["suggestion"]

    def test_no_message_carries_an_absolute_path(self, flagged_ir):
        """Diagnostics are part of the content-checksummed IR, so a message must
        not embed the absolute source path the substrate carries — that would
        make a committed baseline machine-specific and break cross-machine
        staleness."""
        findings = _flagged(flagged_ir)
        assert len(findings) > 0
        for finding in findings:
            assert CORPUS_ROOT not in finding["message"], finding["message"]
            assert ".py" not in finding["message"], finding["message"]

    def test_total_finding_count_is_exact(self, flagged_ir):
        """A pin on the whole corpus: exactly the seven uncovered call-sites
        fire, so a regression that over- or under-emits is caught."""
        assert len(_flagged(flagged_ir)) == 7

    def test_determinism_same_domain_same_findings(self):
        """Same corpus built twice yields identical findings in identical
        order."""

        def build() -> list[dict]:
            domain = Domain(name="UnindexedFilterPathDet", root_path=CORPUS_ROOT)
            domain.register(
                catalog.Order, indexes=[Index("status"), Index("channel", "region")]
            )
            domain.register(catalog.OrderRepository, part_of=catalog.Order)
            domain.init(traverse=False)
            return _flagged(IRBuilder(domain).build())

        first, second = build(), build()
        assert [d["message"] for d in first] == [d["message"] for d in second]
        assert len(first) > 0


class TestUnindexedFilterPathSuppression:
    """All three suppression layers silence a UNINDEXED_FILTER_PATH finding."""

    def _order_with_plain_filter(self, name: str, **register_kwargs) -> dict:
        """Order (no index) + a repository filtering the plain ``name`` field.

        ``register_kwargs`` flow to the aggregate registration, so a test can
        attach ``suppress_checks``. Returns the built IR.
        """
        domain = Domain(name=name, root_path=CORPUS_ROOT)
        domain.register(catalog.Order, **register_kwargs)
        domain.register(catalog.OrderRepository, part_of=catalog.Order)
        domain.init(traverse=False)
        return IRBuilder(domain).build()

    def test_control_domain_has_the_finding(self):
        """Without suppression the plain-field filter is flagged — the control
        the suppression assertions below are measured against."""
        ir = self._order_with_plain_filter("SuppressControl")
        assert any(d["field"] == "name" for d in _flagged(ir))

    def test_suppress_checks_on_aggregate_removes_finding(self):
        """Per-element ``suppress_checks`` resolves against the aggregate FQN in
        ``element`` (the finding is keyed on the aggregate, where the ``Index()``
        fix lives)."""
        ir = self._order_with_plain_filter(
            "SuppressAgg", suppress_checks=["UNINDEXED_FILTER_PATH"]
        )
        assert _flagged(ir) == []

    def test_lint_suppressions_allow_list_grandfathers(self):
        """``[lint].suppressions`` grandfathers the first N findings per code."""
        domain = Domain(name="SuppressAllowList", root_path=CORPUS_ROOT)
        domain.config["lint"] = {"suppressions": {"UNINDEXED_FILTER_PATH": 100}}
        domain.register(catalog.Order)
        domain.register(catalog.OrderRepository, part_of=catalog.Order)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        assert _flagged(ir) == []


@pytest.fixture(scope="module")
def receiver_ir() -> dict:
    """A domain registering the receiver-resolution corpus: a service filtering
    through a repository class (case 1) and through an event class (case 4)."""
    domain = Domain(name="ReceiverCases", root_path=CORPUS_ROOT)
    domain.register(catalog.Order, indexes=[Index("status")])
    domain.register(catalog.OrderRepository, part_of=catalog.Order)
    domain.register(catalog.OrderPlaced, part_of=catalog.Order)
    domain.register(catalog.ReceiverCaseService, part_of=catalog.Order)
    domain.init(traverse=False)
    return IRBuilder(domain).build()


class TestUnindexedFilterPathReceiverResolution:
    """The four target-resolution cases: a receiver that resolves to a
    repository (1) or an aggregate (2), a self-rooted repository query (3), and
    a receiver that resolves to something else (4)."""

    def test_receiver_resolving_to_a_repository_joins_case_1(self, receiver_ir):
        """A ``OrderRepository.filter(...)`` receiver resolves to the registered
        repository, so the target is that repository's aggregate."""
        findings = [
            d for d in _flagged(receiver_ir) if _method_of(d) == "via_repository_class"
        ]
        assert len(findings) == 1, findings
        assert findings[0]["element"] == fqn(catalog.Order)
        assert findings[0]["field"] == "name"

    def test_receiver_resolving_to_a_non_repository_element_is_skipped_case_4(
        self, receiver_ir
    ):
        """A receiver that resolves to a registered element that is neither a
        repository nor an aggregate (here an event) has no join target."""
        assert "via_event_class" not in _flagged_methods(receiver_ir)


class TestUnindexedFilterPathBoundary:
    """Documented false-negative boundaries the rule deliberately does not
    cross."""

    def test_abstract_aggregate_target_not_flagged(self):
        """An abstract aggregate emits no table, so a filter path joined to one
        is not flagged — consistent with the sibling persistence rule's abstract
        skip."""
        domain = Domain(name="AbstractTarget", root_path=CORPUS_ROOT)
        domain.register(catalog.Order, abstract=True)
        domain.register(catalog.OrderRepository, part_of=catalog.Order)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        assert _flagged(ir) == []

    def test_raw_index_does_not_cover_a_filtered_field(self):
        """A ``RawIndex`` carries opaque DDL and no ``fields`` key, so it never
        contributes a covered column — a filter on the field it happens to index
        is still flagged (the rule reads only structured ``Index`` columns)."""
        domain = Domain(name="RawIndexTarget", root_path=CORPUS_ROOT)
        domain.register(
            catalog.Order,
            indexes=[Index.from_sql("postgresql", "CREATE INDEX ix ON order (name)")],
        )
        domain.register(catalog.OrderRepository, part_of=catalog.Order)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()
        # ``filter_plain`` filters ``name``; the RawIndex is not read, so it flags.
        assert any(
            _method_of(d) == "filter_plain" and d["field"] == "name"
            for d in _flagged(ir)
        )
