"""Diagnostics: TestHandlerPersistsAndCallsOut.

The rule is advisory, so its negative cases carry more weight than its positive
one. A check that fires on the shape ADR-0031 tells people to write is a check
people learn to ignore, and the split-across-siblings shape is exactly that.
"""

import pytest

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

    @pytest.mark.parametrize(
        ("handler", "callee"),
        [
            (handler_io_domain.PersistsThenCallsOutOnOneLine, "httpx.post"),
            (handler_io_domain.PersistsThenReachesAnUnambiguousName, "urlopen"),
        ],
        ids=["persist-and-call-on-one-line", "unambiguous-io-name"],
    )
    def test_a_call_after_a_persist_is_flagged(self, handler, callee):
        """A persist and the call on the same physical line, the call second,
        still fires: ordering is on `(line, column)`, not the line alone.
        `urllib.request.urlopen` is in `UNAMBIGUOUS_IO_NAMES` and resolves
        module-rooted, so it counts without the module+verb path, through real
        source and not only in the predicate unit test."""
        domain = _build_handler_io_domain(f"Io{handler.__name__}", handler)

        findings = _findings(IRBuilder(domain).build(), CODE)
        assert len(findings) == 1
        assert callee in findings[0]["message"]

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
    @pytest.mark.parametrize(
        "handler",
        [
            handler_io_domain.OnlyCallsOut,
            handler_io_domain.OnlyPersists,
            handler_io_domain.CallsOutBeforePersisting,
            handler_io_domain.SplitAcrossSiblings,
            handler_io_domain.BuildsAUrlOnly,
            handler_io_domain.BuildsAClientOnly,
            handler_io_domain.AliasedCallOut,
        ],
        ids=[
            "only-calls-out",
            "only-persists",
            "call-before-the-first-persist",
            "persist-and-call-split-across-sibling-methods",
            "pure-string-helper-from-an-io-module",
            "client-constructor-from-an-io-module",
            "unresolvable-call-through-a-local-alias",
        ],
    )
    def test_a_handler_without_the_hazard_is_not_flagged(self, handler):
        """The rule stays silent when a method does only one of the two, and in
        these cases:

        - A call before the first persist runs outside the transaction, which
          opens at the first repository access.
        - One sibling persists and another calls out. This is the remedy the
          rule suggests, so firing here would make the rule self-defeating.
        - `urllib.parse.urlencode` is rooted in an I/O module and does no I/O.
          The module alone is not enough; the call has to be named like a
          request.
        - `requests.Session()` builds a client; it sends nothing.
        - A call through a local alias does not resolve. Reporting nothing keeps
          the verdict reproducible."""
        domain = _build_handler_io_domain(f"Io{handler.__name__}", handler)

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
