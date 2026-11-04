"""Diagnostics: TestInfraImportInDomain."""

import importlib.util

import pytest

from protean import Domain
from protean.core.aggregate import BaseAggregate
from protean.core.value_object import BaseValueObject
from protean.fields.simple import String
from protean.ir.builder import IRBuilder
from protean.utils import fqn
from tests.ir.diagnostics._helpers import (
    _build_infra_domain,
    _infra_findings,
)
from tests.ir.support import (
    infra_from_import_domain,
    infra_guarded_domain,
    infra_import_domain,
)


class TestInfraImportInDomain:
    """INFRA_IMPORT_IN_DOMAIN (opt-in) flags domain elements whose source module
    imports from ``protean.adapters``."""

    def test_default_off_emits_nothing(self):
        """With the flag absent the method returns immediately: no file is
        parsed, no diagnostic is emitted, even though the module does import
        infra."""
        domain = _build_infra_domain("InfraOff")
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_clean_domain_with_flag_on_is_not_flagged(self):
        """An element defined in this test module, which imports protean
        modules but nothing from ``protean.adapters``, is not flagged with the
        rule on."""
        domain = Domain(name="CleanInfra", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}

        @domain.aggregate
        class Order:
            name = String(max_length=50)

        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_per_element_suppression_removes_only_that_element(self):
        domain = _build_infra_domain(
            "InfraSuppress",
            {"check_infra_imports": True},
            suppress_checks=["INFRA_IMPORT_IN_DOMAIN"],
        )
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_import_domain.InfraOrder) not in elements
        # The value object in the same module is untouched by the aggregate's
        # per-element suppression.
        assert fqn(infra_import_domain.Money) in elements

    def test_suppressions_allow_list_grandfathers_first_n(self):
        """Two infra-importing elements with ``suppressions = {code: 1}`` leaves
        exactly one survivor: the deterministically-ranked tail."""
        domain = _build_infra_domain(
            "InfraAllowList",
            {
                "check_infra_imports": True,
                "suppressions": {"INFRA_IMPORT_IN_DOMAIN": 1},
            },
        )
        ir = IRBuilder(domain).build()

        survivors = [d["element"] for d in _infra_findings(ir)]
        assert len(survivors) == 1
        all_elements = sorted(
            [
                fqn(infra_import_domain.InfraOrder),
                fqn(infra_import_domain.Money),
            ]
        )
        # First in (code, element, ...) order is grandfathered; the tail lives.
        assert survivors == all_elements[1:]

    def test_non_cluster_element_is_scanned(self):
        """A repository is not an aggregate-cluster member, yet it lives in the
        infra-importing module. The scan includes *every* registered domain
        element, so the repository is flagged too, not just the aggregate and
        value object inside the cluster."""
        domain = _build_infra_domain("InfraRepo", {"check_infra_imports": True})
        domain.register(
            infra_import_domain.InfraOrderRepository,
            part_of=infra_import_domain.InfraOrder,
        )
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_import_domain.InfraOrderRepository) in elements

    def test_from_import_alias_form_is_detected(self):
        """``from protean import adapters`` (module ``protean``, alias
        ``adapters``) must be caught. The rule inspects imported alias names,
        not only ``ImportFrom.module``."""
        domain = Domain(name="InfraFromForm", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(infra_from_import_domain.FromFormOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        elements = [d["element"] for d in _infra_findings(ir)]
        assert fqn(infra_from_import_domain.FromFormOrder) in elements

    def test_guarded_and_lazy_imports_are_not_flagged(self):
        """An adapter import reachable only under ``TYPE_CHECKING`` or inside a
        method body introduces no module-level runtime coupling, so it must not
        be flagged. Those are the idiomatic ways to avoid coupling."""
        domain = Domain(name="InfraGuarded", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(infra_guarded_domain.GuardedOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    @pytest.mark.parametrize(
        "module_name",
        ["os.no_such_sub", ""],
        ids=["parent-is-not-a-package", "empty-module-name"],
    )
    def test_element_with_no_source_file_is_skipped(self, module_name):
        """When an element's ``__module__`` resolves to no source file, the rule
        skips it without error and the diagnostics pass is not aborted. For
        ``os.no_such_sub``, ``find_spec`` raises because ``os`` is a module, not
        a package. An empty module name is skipped before any lookup."""
        domain = Domain(name="InfraNoSource", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        broken = type(
            "BrokenModuleVO",
            (BaseValueObject,),
            {"__module__": module_name, "amount": String(max_length=5)},
        )
        domain.register(broken)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_unparseable_source_fails_open(self, tmp_path, monkeypatch):
        """When a resolved source file cannot be AST-parsed, the rule fails open:
        the module is treated as not importing infra rather than crashing the
        build. The module imports ``protean.adapters`` when it is loaded, and
        its file is then overwritten with invalid source, so a parse of the
        original source would flag it. The domain's root is the same
        directory, so the walk over the domain's package meets the broken file
        too and skips it."""
        module_name = "infra_unparseable_module"
        source = tmp_path / f"{module_name}.py"
        source.write_text(
            "from protean.adapters.broker.inline import InlineBroker\n"
            "from protean.core.aggregate import BaseAggregate\n"
            "from protean.fields import String\n"
            "\n"
            "\n"
            "class UnparseableOrder(BaseAggregate):\n"
            "    name = String(max_length=50)\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        # Loaded from its file without entering sys.modules, so no other test
        # sees it.
        spec = importlib.util.spec_from_file_location(module_name, source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source.write_text("def broken(:\n")

        domain = Domain(name="InfraUnparseable", root_path=str(tmp_path))
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(module.UnparseableOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_duplicate_fqn_is_scanned_once(self):
        """Two distinct classes sharing a fully-qualified name (same module and
        name, different element buckets) are scanned once, not twice. The
        ``seen`` guard dedupes by FQN, so the infra-importing FQN is flagged a
        single time."""
        domain = Domain(name="InfraDup", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        module = infra_import_domain.__name__
        vo = type(
            "DupElement",
            (BaseValueObject,),
            {"__module__": module, "amount": String(max_length=5)},
        )
        agg = type(
            "DupElement",
            (BaseAggregate,),
            {"__module__": module, "name": String(max_length=5)},
        )
        domain.register(vo)
        domain.register(agg)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        dup_fqn = f"{module}.DupElement"
        assert [d["element"] for d in _infra_findings(ir)].count(dup_fqn) == 1

    def test_the_rule_runs_through_domain_to_ir(self):
        """``IRBuilder`` is not the only entry point: ``Domain.to_ir()`` is what
        the CLI, the hooks and the observatory go through."""
        domain = _build_infra_domain("InfraToIr", {"check_infra_imports": True})

        findings = _infra_findings(domain.to_ir())

        assert sorted(d["element"] for d in findings) == sorted(
            [
                fqn(infra_import_domain.InfraOrder),
                fqn(infra_import_domain.Money),
            ]
        )

    def test_emitted_diagnostics_match_the_frozen_expectation(self):
        """The full emitted payload for the infra fixtures (codes, elements,
        order, levels, messages and rule text), pinned verbatim.

        The expectation was written from the current output. Any later
        change to how source is located, parsed or cached shows up as a diff
        here instead of passing silently.
        """
        domain = _build_infra_domain("InfraFrozen", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        module = infra_import_domain.__name__
        rationale = (
            "Domain elements must not depend on concrete infrastructure "
            "adapters; importing from `protean.adapters` couples the domain "
            "layer to a specific adapter and breaks the ports-and-adapters "
            "boundary."
        )
        fix = (
            "Remove the `protean.adapters` import from the domain module. "
            "Depend on domain-layer abstractions and let the adapter be wired "
            "through the domain's provider configuration instead."
        )
        assert _infra_findings(ir) == [
            {
                "code": "INFRA_IMPORT_IN_DOMAIN",
                "category": "bounded_context",
                "element": f"{module}.InfraOrder",
                "level": "warning",
                "message": (
                    f"Domain element `InfraOrder` (module `{module}`) "
                    "imports from `protean.adapters`."
                ),
                "rule": {"rationale": rationale, "fix": fix},
                "suggestion": fix,
            },
            {
                "code": "INFRA_IMPORT_IN_DOMAIN",
                "category": "bounded_context",
                "element": f"{module}.Money",
                "level": "warning",
                "message": (
                    f"Domain element `Money` (module `{module}`) "
                    "imports from `protean.adapters`."
                ),
                "rule": {"rationale": rationale, "fix": fix},
                "suggestion": fix,
            },
        ]
