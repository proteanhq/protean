"""Opportunity detectors for `protean upgrade-check --opportunities`.

The detectors read the domain's source, so most cases drive the AST helpers over
representative snippets rather than standing up a domain per case, mirroring
`test_uow_upgrade_checks.py`. The near-miss cases matter as much as the positive
ones: a detector that fires on correct code is one people learn to ignore.

The end-to-end walk (SourceProvider over a real package, determinism, and the
CHECK_FAILED isolation) is exercised against a real domain on disk at the bottom.
"""

from __future__ import annotations

import ast
import importlib
import sys

import pytest

from protean import upgrade_opportunities
from protean.upgrade_opportunities import (
    _detect_custom_middleware,
    _detect_queue_status,
    _detect_raw_sql,
    parse_version,
    run_opportunity_checks,
)

# Pinned at the installed version by default: every in-scope detector owns its
# capability, so a pin this high never suppresses one.
OWNS_ALL = parse_version("0.17.0")


def trees(src: str) -> list[tuple[str, ast.Module]]:
    return [("m", ast.parse(src))]


class TestVersionParsing:
    def test_plain_semver(self):
        assert parse_version("0.16.3") == (0, 16, 3)

    def test_missing_patch_reads_as_zero(self):
        assert parse_version("0.16") == (0, 16, 0)

    def test_prerelease_suffix_compares_by_numeric_core(self):
        assert parse_version("0.15.0rc1") == (0, 15, 0)

    def test_ordering_is_numeric_not_lexical(self):
        # A lexical compare would put "0.9.0" above "0.16.0"; a tuple compare
        # does not.
        assert parse_version("0.9.0") < parse_version("0.16.0")


class TestRawSqlDetector:
    def test_from_import_text_is_flagged(self):
        src = (
            "from sqlalchemy import text\n"
            "def q(s):\n"
            "    return s.execute(text('SELECT 1'))\n"
        )
        findings = _detect_raw_sql(trees(src), OWNS_ALL)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.code == "OPPORTUNITY_QUERY_API"
        assert finding.level == "info"
        assert "0.16.0" in finding.detail
        assert "m:3" in finding.detail

    def test_counts_every_site(self):
        src = (
            "from sqlalchemy import text\n"
            "def a(s):\n"
            "    s.execute(text('SELECT 1'))\n"
            "    s.execute(text('SELECT 2'))\n"
        )
        findings = _detect_raw_sql(trees(src), OWNS_ALL)
        assert findings[0].title.startswith("2 raw")

    def test_module_alias_attribute_call_is_flagged(self):
        src = "import sqlalchemy as sa\ndef q(s):\n    s.execute(sa.text('SELECT 1'))\n"
        assert len(_detect_raw_sql(trees(src), OWNS_ALL)) == 1

    def test_aliased_from_import_is_flagged(self):
        src = "from sqlalchemy import text as t\ndef q(s):\n    s.execute(t('x'))\n"
        assert len(_detect_raw_sql(trees(src), OWNS_ALL)) == 1

    def test_clean_domain_gives_no_finding(self):
        src = "def q(repo):\n    return repo.filter(name='x')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL) == []

    def test_local_text_without_sqlalchemy_import_is_not_flagged(self):
        # The import gate is the whole point: a `text()` that is not the
        # sqlalchemy import must stay silent.
        src = "def text(x):\n    return x\ndef q():\n    return text('hi')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL) == []

    def test_text_attribute_on_an_unrelated_object_is_not_flagged(self):
        # `widget.text(...)` is an attribute call whose root is not the
        # sqlalchemy module, so it is not a raw-SQL site.
        src = "def q(widget):\n    return widget.text('hi')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL) == []


class TestCustomMiddlewareDetector:
    def test_base_http_middleware_subclass_is_flagged(self):
        src = (
            "from starlette.middleware.base import BaseHTTPMiddleware\n"
            "class ContextMiddleware(BaseHTTPMiddleware):\n"
            "    pass\n"
        )
        findings = _detect_custom_middleware(trees(src), OWNS_ALL)
        assert len(findings) == 1
        assert findings[0].code == "OPPORTUNITY_DOMAIN_CONTEXT_MIDDLEWARE"
        assert "0.15.0" in findings[0].detail

    def test_async_dispatch_method_is_flagged(self):
        src = (
            "class Middleware:\n"
            "    async def dispatch(self, request, call_next):\n"
            "        return await call_next(request)\n"
        )
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL)) == 1

    def test_add_middleware_of_a_custom_class_is_flagged(self):
        src = "def wire(app):\n    app.add_middleware(MyMiddleware)\n"
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL)) == 1

    def test_adding_domain_context_middleware_is_not_flagged(self):
        # The framework's own middleware is the answer, not an opportunity.
        src = "def wire(app):\n    app.add_middleware(DomainContextMiddleware)\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL) == []

    def test_a_plain_class_is_not_flagged(self):
        src = "class Order:\n    async def dispatch(self):\n        return None\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL) == []


class TestQueueStatusDetector:
    def test_queue_like_status_field_is_flagged(self):
        src = (
            "class Job:\n"
            "    status = String(choices=['pending', 'processing', 'done', 'failed'])\n"
        )
        findings = _detect_queue_status(trees(src), OWNS_ALL)
        assert len(findings) == 1
        assert findings[0].code == "OPPORTUNITY_OUTBOX"
        assert "0.14.0" in findings[0].detail

    def test_annotated_assignment_is_flagged(self):
        src = "class Job:\n    state: str = Field(choices=['queued', 'sent'])\n"
        assert len(_detect_queue_status(trees(src), OWNS_ALL)) == 1

    def test_non_queue_status_choices_are_not_flagged(self):
        # A domain `status` with business choices is not a work queue.
        src = "class User:\n    status = String(choices=['active', 'inactive'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL) == []

    def test_single_queue_token_is_not_enough(self):
        # One overlapping token is too loose; a match needs at least two.
        src = "class User:\n    status = String(choices=['pending', 'approved'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL) == []

    def test_enum_choices_are_not_read(self):
        # An enum reference has no literal members to inspect, so it stays silent.
        src = "class Job:\n    status = String(choices=JobStatus)\n"
        assert _detect_queue_status(trees(src), OWNS_ALL) == []

    def test_non_status_field_with_queue_words_is_not_flagged(self):
        src = "class Job:\n    label = String(choices=['pending', 'done', 'failed'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL) == []

    def test_other_field_keywords_are_skipped_before_choices(self):
        # A field carrying more than `choices` still matches on its choices.
        src = (
            "class Job:\n"
            "    status = String(required=True, "
            "choices=['pending', 'processing', 'done'])\n"
        )
        assert len(_detect_queue_status(trees(src), OWNS_ALL)) == 1

    def test_a_non_call_assignment_is_ignored(self):
        # A plain constant assignment beside the field is not a field at all.
        src = (
            "DEFAULT = 'pending'\n"
            "class Job:\n"
            "    status = String(choices=['pending', 'processing', 'done'])\n"
        )
        assert len(_detect_queue_status(trees(src), OWNS_ALL)) == 1


class TestVersionGate:
    _SRC = (
        "from sqlalchemy import text\n"
        "def q(s):\n"
        "    return s.execute(text('SELECT 1'))\n"
    )

    def test_pinned_below_the_release_suppresses_the_finding(self):
        # The query API arrived in 0.16.0; a domain pinned to 0.15.0 does not own
        # it yet, so there is nothing to claim.
        assert _detect_raw_sql(trees(self._SRC), parse_version("0.15.0")) == []

    def test_pinned_at_the_release_surfaces_the_finding(self):
        assert len(_detect_raw_sql(trees(self._SRC), parse_version("0.16.0"))) == 1

    def test_pinned_above_the_release_surfaces_the_finding(self):
        assert len(_detect_raw_sql(trees(self._SRC), parse_version("0.17.2"))) == 1

    def test_middleware_gate_suppresses_below_its_release(self):
        # DomainContextMiddleware arrived in 0.15.0.
        src = (
            "from starlette.middleware.base import BaseHTTPMiddleware\n"
            "class M(BaseHTTPMiddleware):\n"
            "    pass\n"
        )
        assert _detect_custom_middleware(trees(src), parse_version("0.14.0")) == []

    def test_outbox_gate_suppresses_below_its_release(self):
        # The outbox arrived in 0.14.0.
        src = "class Job:\n    status = String(choices=['pending', 'done', 'failed'])\n"
        assert _detect_queue_status(trees(src), parse_version("0.13.1")) == []


@pytest.mark.no_test_domain
class TestAgainstRealSource:
    """Drive `run_opportunity_checks` over a real domain package on disk."""

    def _domain_at(self, tmp_path, body: str):
        pkg = tmp_path / "oppapp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "domain.py").write_text(body)
        sys.path.insert(0, str(tmp_path))
        try:
            module = importlib.import_module("oppapp.domain")
            module.domain.init(traverse=False)
            return module.domain
        finally:
            sys.path.remove(str(tmp_path))

    def teardown_method(self):
        for name in [m for m in sys.modules if m.startswith("oppapp")]:
            del sys.modules[name]

    _BODY = (
        "from sqlalchemy import text\n"
        "from protean import Domain\n"
        "from protean.fields import String\n"
        "\n"
        "domain = Domain(name='Opp')\n"
        "\n"
        "@domain.aggregate\n"
        "class Job:\n"
        "    status = String(choices=['pending', 'processing', 'done', 'failed'])\n"
        "\n"
        "def legacy(session):\n"
        "    return session.execute(text('SELECT 1'))\n"
    )

    def test_walk_finds_opportunities_in_real_source(self, tmp_path):
        domain = self._domain_at(tmp_path, self._BODY)
        with domain.domain_context():
            findings = run_opportunity_checks(domain, "0.17.0")
        codes = {f.code for f in findings}
        assert "OPPORTUNITY_QUERY_API" in codes
        assert "OPPORTUNITY_OUTBOX" in codes

    def test_clean_domain_yields_no_opportunities(self, tmp_path):
        body = (
            "from protean import Domain\n"
            "from protean.fields import String\n"
            "\n"
            "domain = Domain(name='Opp')\n"
            "\n"
            "@domain.aggregate\n"
            "class User:\n"
            "    name = String()\n"
        )
        domain = self._domain_at(tmp_path, body)
        with domain.domain_context():
            findings = run_opportunity_checks(domain, "0.17.0")
        assert findings == []

    def test_same_input_gives_identical_findings(self, tmp_path):
        domain = self._domain_at(tmp_path, self._BODY)
        with domain.domain_context():
            first = [f.as_dict() for f in run_opportunity_checks(domain, "0.17.0")]
            second = [f.as_dict() for f in run_opportunity_checks(domain, "0.17.0")]
        assert first == second
        assert first, "expected at least one finding to compare"

    def test_a_raising_detector_is_isolated(self, tmp_path, monkeypatch):
        def boom(trees, pinned):
            raise RuntimeError("detector blew up")

        monkeypatch.setattr(
            upgrade_opportunities,
            "_DETECTORS",
            (boom, upgrade_opportunities._detect_raw_sql),
        )
        domain = self._domain_at(tmp_path, self._BODY)
        with domain.domain_context():
            findings = run_opportunity_checks(domain, "0.17.0")
        codes = {f.code for f in findings}
        # The failure is surfaced, and the surviving detector still ran.
        assert "CHECK_FAILED" in codes
        assert "OPPORTUNITY_QUERY_API" in codes
