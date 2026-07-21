"""Diagnostics: TestAdapterCallInDomain."""

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _adapter_findings,
    _build_adapter_call_domain,
)
from tests.ir.support import adapter_call_domain


class TestAdapterCallInDomain:
    """ADAPTER_CALL_IN_DOMAIN (opt-in) flags a domain element whose method body
    calls a statically-resolved ``protean.adapters.*`` symbol."""

    def test_on_path_flags_resolved_adapter_call(self):
        """A method reaching an adapter through ``import protean`` attribute
        access is flagged with the enriched diagnostic shape."""
        domain = _build_adapter_call_domain("AdapterOn", {"check_adapter_calls": True})
        ir = IRBuilder(domain).build()

        agg_fqn = fqn(adapter_call_domain.AdapterCallOrder)
        findings = [d for d in _adapter_findings(ir) if d["element"] == agg_fqn]
        assert len(findings) == 1
        d = findings[0]
        assert d["level"] == "warning"
        assert d["category"] == "bounded_context"
        assert d["element"] == agg_fqn
        assert "provision" in d["message"]
        assert "protean.adapters.broker.inline.InlineBroker" in d["message"]
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]
        assert d["suggestion"] == d["rule"]["fix"]

    def test_this_rule_catches_what_the_import_rule_misses(self):
        """The positive fixture reaches the adapter through ``import protean``
        attribute access. INFRA_IMPORT_IN_DOMAIN's module-level name-prefix check
        does not see it (no top-level ``protean.adapters`` import), so with both
        rules on only ADAPTER_CALL_IN_DOMAIN fires — proving the call-site rule's
        incremental value, not just its overlap."""
        domain = _build_adapter_call_domain(
            "AdapterUnique",
            {"check_adapter_calls": True, "check_infra_imports": True},
        )
        ir = IRBuilder(domain).build()

        agg_fqn = fqn(adapter_call_domain.AdapterCallOrder)
        codes = {d["code"] for d in ir["diagnostics"] if d.get("element") == agg_fqn}
        assert "ADAPTER_CALL_IN_DOMAIN" in codes
        assert "INFRA_IMPORT_IN_DOMAIN" not in codes

    def test_default_off_emits_nothing(self):
        """With the flag absent the method returns immediately — no body is
        parsed, no diagnostic emitted, even though the method calls an adapter."""
        domain = _build_adapter_call_domain("AdapterOff")
        ir = IRBuilder(domain).build()

        assert _adapter_findings(ir) == []

    def test_unresolved_callee_is_not_flagged(self):
        """The conservative half: an adapter reached through a function-local
        import, or a fetched local-variable receiver, does not statically
        resolve, so it is skipped rather than guessed at."""
        domain = _build_adapter_call_domain(
            "AdapterUnresolved",
            {"check_adapter_calls": True},
            elements=(
                adapter_call_domain.LocalImportOrder,
                adapter_call_domain.InjectedReceiverOrder,
            ),
        )
        ir = IRBuilder(domain).build()

        assert _adapter_findings(ir) == []

    def test_non_registered_class_is_out_of_scope(self):
        """A class with an identical adapter call that is never registered is
        never visited — the rule is domain-scoped, so it emits nothing when only
        a clean element is registered alongside it."""
        domain = _build_adapter_call_domain(
            "AdapterScope",
            {"check_adapter_calls": True},
            elements=(adapter_call_domain.CleanOrder,),
        )
        ir = IRBuilder(domain).build()

        # ``UnregisteredHelper`` lives in the same module and calls an adapter,
        # but is not registered, so no finding names it (or anything else).
        assert _adapter_findings(ir) == []

    def test_clean_self_rooted_call_is_not_flagged(self):
        """A self-rooted repository/DAO call (``self._dao.filter(...)``) resolves
        to no FQN and names no adapter, so it is not over-flagged."""
        domain = _build_adapter_call_domain(
            "AdapterClean",
            {"check_adapter_calls": True},
            elements=(adapter_call_domain.CleanOrder,),
        )
        ir = IRBuilder(domain).build()

        assert _adapter_findings(ir) == []

    def test_multi_site_emits_one_per_call_in_source_order(self):
        """A method with two adapter calls emits two diagnostics, in source
        order — the second (Redis, later line) after the first (inline)."""
        domain = _build_adapter_call_domain(
            "AdapterMulti",
            {"check_adapter_calls": True},
            elements=(adapter_call_domain.MultiCallOrder,),
        )
        ir = IRBuilder(domain).build()

        agg_fqn = fqn(adapter_call_domain.MultiCallOrder)
        findings = [d for d in _adapter_findings(ir) if d["element"] == agg_fqn]
        assert len(findings) == 2
        # Source order: inline broker call precedes the redis broker call.
        assert "InlineBroker" in findings[0]["message"]
        assert "RedisBroker" in findings[1]["message"]

    def test_multiple_elements_emit_in_fqn_order(self):
        """Two registered elements each emit their findings; the emission order
        over elements is fqn-sorted (``AdapterCallOrder`` before
        ``MultiCallOrder``)."""
        domain = _build_adapter_call_domain(
            "AdapterFqnOrder",
            {"check_adapter_calls": True},
            elements=(
                adapter_call_domain.MultiCallOrder,
                adapter_call_domain.AdapterCallOrder,
            ),
        )
        ir = IRBuilder(domain).build()

        elements_in_order = [d["element"] for d in _adapter_findings(ir)]
        agg = fqn(adapter_call_domain.AdapterCallOrder)
        multi = fqn(adapter_call_domain.MultiCallOrder)
        # AdapterCallOrder (1 finding) sorts before MultiCallOrder (2 findings).
        assert elements_in_order == [agg, multi, multi]

    def test_per_element_suppression_removes_only_that_element(self):
        """``suppress_checks`` on one element silences only its findings; a
        second infra-calling element in the domain is untouched."""
        domain = Domain(name="AdapterSuppress", root_path=".")
        domain.config["lint"] = {"check_adapter_calls": True}
        domain.register(
            adapter_call_domain.AdapterCallOrder,
            suppress_checks=["ADAPTER_CALL_IN_DOMAIN"],
        )
        domain.register(adapter_call_domain.MultiCallOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = {d["element"] for d in _adapter_findings(ir)}
        assert fqn(adapter_call_domain.AdapterCallOrder) not in elements
        assert fqn(adapter_call_domain.MultiCallOrder) in elements

    def test_suppressions_allow_list_grandfathers_first_n(self):
        """``suppressions = {code: 1}`` grandfathers exactly the first finding in
        the deterministic ``(code, element, ...)`` order, leaving the tail. With
        three findings across two elements, one is silenced and two survive."""
        domain = _build_adapter_call_domain(
            "AdapterAllowList",
            {
                "check_adapter_calls": True,
                "suppressions": {"ADAPTER_CALL_IN_DOMAIN": 1},
            },
            elements=(
                adapter_call_domain.AdapterCallOrder,
                adapter_call_domain.MultiCallOrder,
            ),
        )
        ir = IRBuilder(domain).build()

        survivors = [d["element"] for d in _adapter_findings(ir)]
        # AdapterCallOrder's single finding sorts first and is grandfathered;
        # MultiCallOrder's two findings are the deterministic tail that survives.
        assert survivors == [fqn(adapter_call_domain.MultiCallOrder)] * 2

    def test_duplicate_fqn_is_scanned_once(self):
        """Two classes sharing a fully-qualified name (same module and name,
        different element buckets) are scanned once — the ``seen`` guard dedupes
        by FQN, so the source's adapter call is flagged a single time, not
        twice."""
        domain = Domain(name="AdapterDup", root_path=".")
        domain.config["lint"] = {"check_adapter_calls": True}
        module = adapter_call_domain.__name__
        # Both map to the real ``AdapterCallOrder`` source (which calls an
        # adapter), so without the dedupe the call would be flagged twice.
        vo = type(
            "AdapterCallOrder",
            (BaseValueObject,),
            {"__module__": module, "amount": String(max_length=5)},
        )
        agg = type(
            "AdapterCallOrder",
            (BaseAggregate,),
            {"__module__": module, "name": String(max_length=5)},
        )
        domain.register(vo)
        domain.register(agg)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        dup_fqn = f"{module}.AdapterCallOrder"
        assert [d["element"] for d in _adapter_findings(ir)].count(dup_fqn) == 1

    def test_unresolvable_module_fails_open(self):
        """An element whose ``__module__`` resolves to no source file yields
        empty facts — the rule emits nothing and the build is not aborted."""
        domain = Domain(name="AdapterFailOpen", root_path=".")
        domain.config["lint"] = {"check_adapter_calls": True}
        broken = type(
            "BrokenAdapterVO",
            (BaseValueObject,),
            {"__module__": "os.no_such_sub", "amount": String(max_length=5)},
        )
        domain.register(broken)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _adapter_findings(ir) == []
        # Build completed and produced a diagnostics list (not aborted).
        assert isinstance(ir["diagnostics"], list)

    def test_the_rule_runs_through_domain_to_ir(self):
        """``IRBuilder`` is not the only entry point: ``Domain.to_ir()`` is what
        the CLI, the hooks and the observatory go through, and the rule fires
        there too."""
        domain = _build_adapter_call_domain(
            "AdapterToIr", {"check_adapter_calls": True}
        )

        findings = _adapter_findings(domain.to_ir())

        assert [d["element"] for d in findings] == [
            fqn(adapter_call_domain.AdapterCallOrder)
        ]

    def test_emitted_diagnostic_matches_the_frozen_expectation(self):
        """The full emitted payload for the positive fixture — code, element,
        level, message and rule text — pinned verbatim.

        A characterization test: any later change to how call-sites are located
        or messaged shows up as a diff here instead of passing silently."""
        domain = _build_adapter_call_domain(
            "AdapterFrozen", {"check_adapter_calls": True}
        )
        ir = IRBuilder(domain).build()

        module = adapter_call_domain.__name__
        callee = "protean.adapters.broker.inline.InlineBroker"
        line = (
            adapter_call_domain.AdapterCallOrder.provision.__code__.co_firstlineno + 1
        )
        rationale = (
            "Domain elements must not depend on concrete infrastructure "
            "adapters; calling into `protean.adapters` from a domain method "
            "couples the domain layer to a specific adapter at runtime and "
            "breaks the ports-and-adapters boundary."
        )
        fix = (
            "Remove the `protean.adapters` call from the domain method. "
            "Depend on domain-layer abstractions and let the adapter be "
            "wired through the domain's provider configuration instead."
        )
        assert _adapter_findings(ir) == [
            {
                "code": "ADAPTER_CALL_IN_DOMAIN",
                "category": "bounded_context",
                "element": f"{module}.AdapterCallOrder",
                "level": "warning",
                "message": (
                    f"Domain element `AdapterCallOrder` calls `{callee}` "
                    f"in method `provision` (line {line}), coupling the "
                    f"domain to `protean.adapters`."
                ),
                "rule": {"rationale": rationale, "fix": fix},
                "suggestion": fix,
            }
        ]
