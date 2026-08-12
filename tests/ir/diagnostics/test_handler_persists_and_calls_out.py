"""Diagnostics: TestHandlerPersistsAndCallsOut.

The rule is advisory, so its negative cases carry more weight than its positive
one. A check that fires on the shape ADR-0031 tells people to write is a check
people learn to ignore, and the split-across-siblings shape is exactly that.
"""

from protean.ir.builder import IRBuilder
from protean.ir.diagnostics import REGISTRY, DiagnosticCode
from protean.utils import fqn
from tests.ir.diagnostics._helpers import _build_handler_io_domain, _findings
from tests.ir.support import handler_io_domain

CODE = DiagnosticCode.HANDLER_PERSISTS_AND_CALLS_OUT


class TestHandlerPersistsAndCallsOut:
    def test_a_method_doing_both_is_flagged(self):
        domain = _build_handler_io_domain(
            "IoBoth", handler_io_domain.PersistsAndCallsOut
        )
        ir = IRBuilder(domain).build()

        findings = _findings(ir, CODE)
        assert len(findings) == 1
        d = findings[0]
        assert d["element"] == fqn(handler_io_domain.PersistsAndCallsOut)
        assert d["level"] == "info"
        assert d["category"] == "persistence"
        assert "persists_and_calls_out" in d["message"]
        assert "httpx.post" in d["message"]
        assert d["rule"]["rationale"]
        assert d["rule"]["fix"]

    def test_it_is_advisory_rather_than_a_warning(self):
        """A warning would push people to silence it on code the docs endorse."""
        assert REGISTRY[CODE].level == "info"

    def test_persist_and_call_on_one_line_is_ordered_by_column(self):
        """A persist and the call on the same physical line, the call second,
        still fires: ordering is on `(line, column)`, not the line alone."""
        domain = _build_handler_io_domain(
            "IoOneLine", handler_io_domain.PersistsThenCallsOutOnOneLine
        )

        findings = _findings(IRBuilder(domain).build(), CODE)
        assert len(findings) == 1
        assert "httpx.post" in findings[0]["message"]

    def test_an_unambiguous_io_name_fires_end_to_end(self):
        """`urllib.request.urlopen` is in `UNAMBIGUOUS_IO_NAMES` and resolves
        module-rooted, so it counts without the module+verb path. This proves at
        least one unambiguous name works through real source, not just the
        predicate unit test."""
        domain = _build_handler_io_domain(
            "IoUrlopen", handler_io_domain.PersistsThenReachesAnUnambiguousName
        )

        findings = _findings(IRBuilder(domain).build(), CODE)
        assert len(findings) == 1
        assert "urlopen" in findings[0]["message"]

    def test_a_process_manager_method_is_flagged_too(self):
        """The PM dispatch loop wraps each method in its own Unit of Work
        (`process_manager.py`), so the hazard is identical to an event
        handler's. ADR-0031 defers process managers on sibling *failure*
        isolation, which is a state-transition question and a different one."""
        domain = _build_handler_io_domain("IoPm", handler_io_domain.IoFulfillmentPM)
        ir = IRBuilder(domain).build()

        findings = _findings(ir, CODE)
        assert len(findings) == 1
        assert findings[0]["element"] == fqn(handler_io_domain.IoFulfillmentPM)
        assert "on_placed" in findings[0]["message"]

    def test_the_fix_names_the_process_manager_alternative(self):
        """Splitting a PM method in two records two transitions where the author
        wanted one, so the generic remedy misfires there."""
        assert "process manager" in REGISTRY[CODE].fix


class TestTheRuleStaysSilent:
    def test_a_method_that_only_calls_out(self):
        domain = _build_handler_io_domain("IoOut", handler_io_domain.OnlyCallsOut)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_call_that_runs_before_the_first_persist(self):
        """The transaction opens at the first repository access, so a call
        before it runs outside the transaction and is not the hazard."""
        domain = _build_handler_io_domain(
            "IoBefore", handler_io_domain.CallsOutBeforePersisting
        )

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_method_that_only_persists(self):
        domain = _build_handler_io_domain("IoPersist", handler_io_domain.OnlyPersists)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_the_split_shape_the_adr_prescribes(self):
        """One sibling persists, another calls out. This is the remedy the rule
        itself suggests, so firing here would make the rule self-defeating."""
        domain = _build_handler_io_domain(
            "IoSplit", handler_io_domain.SplitAcrossSiblings
        )

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_pure_string_helper_from_an_io_module(self):
        """`urllib.parse.urlencode` is rooted in an I/O module and does no I/O.
        The module alone is not enough; the call has to be named like a
        request."""
        domain = _build_handler_io_domain("IoUrl", handler_io_domain.BuildsAUrlOnly)

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_a_client_constructor_from_an_io_module(self):
        """`requests.Session()` builds a client; it sends nothing."""
        domain = _build_handler_io_domain(
            "IoClient", handler_io_domain.BuildsAClientOnly
        )

        assert _findings(IRBuilder(domain).build(), CODE) == []

    def test_an_unresolvable_call_is_not_guessed_at(self):
        """The call goes through a local alias, so its callee does not resolve.
        Reporting nothing is what keeps the verdict reproducible."""
        domain = _build_handler_io_domain("IoAlias", handler_io_domain.AliasedCallOut)

        assert _findings(IRBuilder(domain).build(), CODE) == []


class TestSuppression:
    def test_suppress_checks_silences_it_on_that_handler(self):
        """The rule writes no suppression logic of its own; `_apply_suppressions`
        handles it centrally, and this pins that the rule inherits it."""
        domain = _build_handler_io_domain(
            "IoSuppressed", handler_io_domain.PersistsAndCallsOut
        )
        handler = handler_io_domain.PersistsAndCallsOut
        original = handler.meta_.suppress_checks
        handler.meta_.suppress_checks = (CODE.value,)
        try:
            findings = _findings(IRBuilder(domain).build(), CODE)
        finally:
            handler.meta_.suppress_checks = original

        assert findings == []
