"""Diagnostics: TestAdapterCallInDomain."""

import pytest

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

    def test_this_rule_catches_what_the_import_rule_misses(self):
        """The positive fixture reaches the adapter through ``import protean``
        attribute access. INFRA_IMPORT_IN_DOMAIN's module-level name-prefix check
        does not see it (no top-level ``protean.adapters`` import), so with both
        rules on only ADAPTER_CALL_IN_DOMAIN fires. The call-site rule finds
        something the import rule does not."""
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
        """With the flag absent the method returns immediately: no body is
        parsed, no diagnostic emitted, even though the method calls an adapter."""
        domain = _build_adapter_call_domain("AdapterOff")
        ir = IRBuilder(domain).build()

        assert _adapter_findings(ir) == []

    @pytest.mark.parametrize(
        "silent",
        [
            adapter_call_domain.InjectedReceiverOrder,
            adapter_call_domain.CleanOrder,
            adapter_call_domain.SiblingPrefixOrder,
        ],
        ids=[
            "adapter-on-a-fetched-local-receiver",
            "self-rooted-dao-call-and-non-adapter-call",
            "callee-in-a-sibling-package-with-the-same-prefix",
        ],
    )
    def test_call_that_does_not_resolve_to_an_adapter_is_not_flagged(self, silent):
        """The rule flags only a call that statically resolves into the
        ``protean.adapters`` package. It skips an adapter reached through a
        fetched local-variable receiver (it cannot resolve, so it is not
        guessed at), a self-rooted DAO call, a resolved call to a non-adapter
        such as ``protean.utils.fqn``, and a callee in ``protean.adaptersfoo``,
        which shares the string prefix but is a different package.

        ``AdapterCallOrder`` is registered beside each case and must still be
        flagged, so an empty result cannot pass when the rule did not run."""
        domain = _build_adapter_call_domain(
            "AdapterSilent",
            {"check_adapter_calls": True},
            elements=(adapter_call_domain.AdapterCallOrder, silent),
        )
        ir = IRBuilder(domain).build()

        flagged = {d["element"] for d in _adapter_findings(ir)}
        assert flagged == {fqn(adapter_call_domain.AdapterCallOrder)}
        assert fqn(silent) not in flagged

    @pytest.mark.parametrize(
        "element",
        [adapter_call_domain.LocalImportOrder, adapter_call_domain.AdapterCallMoney],
        ids=["aggregate-with-function-local-import-alias", "value-object"],
    )
    def test_adapter_call_is_flagged_with_the_adapter_fqn(self, element):
        """The rule flags an adapter call bound by an aliased import inside the
        method, and it flags any registered element type, so a value object's
        method that calls an adapter is flagged like an aggregate's. The
        message names the method and the adapter's FQN."""
        domain = _build_adapter_call_domain(
            "AdapterFlagged",
            {"check_adapter_calls": True},
            elements=(element,),
        )
        ir = IRBuilder(domain).build()

        element_fqn = fqn(element)
        findings = [d for d in _adapter_findings(ir) if d["element"] == element_fqn]
        assert len(findings) == 1
        assert "provision" in findings[0]["message"]
        assert "protean.adapters.broker.inline.InlineBroker" in findings[0]["message"]

    def test_multi_site_emits_one_per_call_in_source_order(self):
        """A method with two adapter calls emits two diagnostics, in source
        order: the second (Redis, later line) after the first (inline)."""
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
        different element buckets) are scanned once. The ``seen`` guard dedupes
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
        empty facts. The rule emits nothing and the build is not aborted."""
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
        """The full emitted payload for the positive fixture (code, element,
        level, message and rule text), pinned verbatim.

        Any later change to how call-sites are located
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
