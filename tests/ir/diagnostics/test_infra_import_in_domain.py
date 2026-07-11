"""Diagnostics: TestInfraImportInDomain."""

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

    def test_on_path_flags_infra_importing_aggregate(self):
        domain = _build_infra_domain("InfraOn", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        agg_fqn = fqn(infra_import_domain.InfraOrder)
        agg = [d for d in _infra_findings(ir) if d["element"] == agg_fqn]
        assert len(agg) == 1
        d = agg[0]
        assert d["level"] == "warning"
        assert d["category"] == "bounded_context"
        assert infra_import_domain.InfraOrder.__module__ in d["message"]
        assert "protean.adapters" in d["message"]

    def test_emits_once_per_element_in_the_module(self):
        """The aggregate and the value object both live in the infra-importing
        module, so each is flagged with its own FQN."""
        domain = _build_infra_domain("InfraPerElement", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        elements = sorted(d["element"] for d in _infra_findings(ir))
        assert elements == sorted(
            [
                fqn(infra_import_domain.InfraOrder),
                fqn(infra_import_domain.Money),
            ]
        )

    def test_default_off_emits_nothing(self):
        """With the flag absent the method returns immediately — no file is
        parsed, no diagnostic is emitted, even though the module does import
        infra."""
        domain = _build_infra_domain("InfraOff")
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_clean_domain_with_flag_on_is_not_flagged(self):
        """An element module importing only ``protean.fields`` (this test
        module) must not be flagged, even with the rule on — no over-flagging on
        legitimate framework imports."""
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
        exactly one survivor — the deterministically-ranked tail."""
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
        infra-importing module. The scan covers *every* registered domain
        element, so the repository is flagged too — not just the aggregate and
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
        ``adapters``) must be caught — the rule inspects imported alias names,
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
        be flagged — those are the idiomatic ways to avoid coupling."""
        domain = Domain(name="InfraGuarded", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        domain.register(infra_guarded_domain.GuardedOrder)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_unresolvable_module_fails_open(self):
        """When ``find_spec`` raises (e.g. a ``__module__`` whose parent is not a
        package), the rule fails open — the module is skipped, no diagnostic is
        emitted, and the diagnostics pass is not aborted."""
        domain = Domain(name="InfraUnresolvable", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        # ``os`` is a module, not a package, so ``find_spec('os.no_such_sub')``
        # raises ModuleNotFoundError.
        broken = type(
            "BrokenModuleVO",
            (BaseValueObject,),
            {"__module__": "os.no_such_sub", "amount": String(max_length=5)},
        )
        domain.register(broken)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_unparseable_source_fails_open(self, monkeypatch):
        """When a resolved source file cannot be AST-parsed, the rule fails open:
        the module is treated as not importing infra rather than crashing the
        build."""
        monkeypatch.setattr(
            "protean.ir.builder.ast.parse",
            lambda *a, **k: (_ for _ in ()).throw(SyntaxError("boom")),
        )
        domain = _build_infra_domain("InfraUnparseable", {"check_infra_imports": True})
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []

    def test_duplicate_fqn_is_scanned_once(self):
        """Two distinct classes sharing a fully-qualified name (same module and
        name, different element buckets) are scanned once, not twice — the
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

    def test_element_without_module_is_skipped(self):
        """An element whose ``__module__`` is empty contributes no source file to
        scan, so it is skipped without error."""
        domain = Domain(name="InfraNoModule", root_path=".")
        domain.config["lint"] = {"check_infra_imports": True}
        no_module = type(
            "NoModuleVO",
            (BaseValueObject,),
            {"__module__": "", "amount": String(max_length=5)},
        )
        domain.register(no_module)
        domain.init(traverse=False)
        ir = IRBuilder(domain).build()

        assert _infra_findings(ir) == []
