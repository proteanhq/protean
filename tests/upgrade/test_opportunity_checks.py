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
from protean.exceptions import ConfigurationError
from protean.upgrade_opportunities import (
    _detect_custom_middleware,
    _detect_default_sanitize,
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


class _StubDomain:
    """Stands in for a Domain in the detector unit tests, which drive detectors
    on in-memory source. Only ``config`` is read."""

    def __init__(self, config=None):
        self.config = config if config is not None else {}


# A domain that sets no ``[field_defaults]`` override, so the framework default
# (``sanitize=False``) applies and the sanitize detector is not suppressed.
NO_DEFAULTS = _StubDomain()


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
        findings = _detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)
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
        findings = _detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)
        assert findings[0].title.startswith("2 raw")

    def test_module_alias_attribute_call_is_flagged(self):
        src = "import sqlalchemy as sa\ndef q(s):\n    s.execute(sa.text('SELECT 1'))\n"
        assert len(_detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_aliased_from_import_is_flagged(self):
        src = "from sqlalchemy import text as t\ndef q(s):\n    s.execute(t('x'))\n"
        assert len(_detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_qualified_sqlalchemy_sql_text_is_flagged(self):
        # `sqlalchemy.sql.text(...)` reaches the same `text` through the module
        # path, so the root of the chain is the bound `sqlalchemy` alias.
        src = "import sqlalchemy\ndef q(s):\n    s.execute(sqlalchemy.sql.text('x'))\n"
        assert len(_detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_unrelated_imports_do_not_break_text_detection(self):
        # An unrelated `import` and a non-`text` name in the sqlalchemy import
        # are both skipped while `text` is still bound and matched.
        src = (
            "import os\n"
            "from sqlalchemy import select, text\n"
            "def q(s):\n"
            "    return s.execute(text('SELECT 1'))\n"
        )
        assert len(_detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_clean_domain_gives_no_finding(self):
        src = "def q(repo):\n    return repo.filter(name='x')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_local_text_without_sqlalchemy_import_is_not_flagged(self):
        # The import gate is the whole point: a `text()` that is not the
        # sqlalchemy import must stay silent.
        src = "def text(x):\n    return x\ndef q():\n    return text('hi')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_text_attribute_on_an_unrelated_object_is_not_flagged(self):
        # `widget.text(...)` is an attribute call whose root is not the
        # sqlalchemy module, so it is not a raw-SQL site.
        src = "def q(widget):\n    return widget.text('hi')\n"
        assert _detect_raw_sql(trees(src), OWNS_ALL, NO_DEFAULTS) == []


class TestCustomMiddlewareDetector:
    def test_base_http_middleware_subclass_is_flagged(self):
        src = (
            "from starlette.middleware.base import BaseHTTPMiddleware\n"
            "class ContextMiddleware(BaseHTTPMiddleware):\n"
            "    pass\n"
        )
        findings = _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS)
        assert len(findings) == 1
        assert findings[0].code == "OPPORTUNITY_DOMAIN_CONTEXT_MIDDLEWARE"
        assert "0.15.0" in findings[0].detail

    def test_async_dispatch_method_is_flagged(self):
        src = (
            "class Middleware:\n"
            "    async def dispatch(self, request, call_next):\n"
            "        return await call_next(request)\n"
        )
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_add_middleware_of_a_custom_class_is_flagged(self):
        src = "def wire(app):\n    app.add_middleware(MyMiddleware)\n"
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_adding_domain_context_middleware_is_not_flagged(self):
        # The framework's own middleware is the answer, not an opportunity.
        src = "def wire(app):\n    app.add_middleware(DomainContextMiddleware)\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_standard_framework_middlewares_are_not_flagged(self):
        # CORS/gzip/etc. are the ASGI stack's own middlewares, not hand-rolled
        # capability. DomainContextMiddleware does not replace them, so
        # registering one is correct code and must stay silent.
        src = (
            "def wire(app):\n"
            "    app.add_middleware(CORSMiddleware)\n"
            "    app.add_middleware(GZipMiddleware)\n"
            "    app.add_middleware(TrustedHostMiddleware)\n"
        )
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_qualified_base_http_middleware_subclass_is_flagged(self):
        # Subclassing through the module path is the same middleware.
        src = (
            "import starlette.middleware.base\n"
            "class ContextMiddleware(starlette.middleware.base.BaseHTTPMiddleware):\n"
            "    pass\n"
        )
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_qualified_framework_middlewares_are_not_flagged(self):
        # Registering through the module path is still the stack's own middleware.
        src = (
            "import starlette.middleware.cors\n"
            "def wire(app):\n"
            "    app.add_middleware(starlette.middleware.cors.CORSMiddleware)\n"
        )
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_aliased_standard_middleware_is_not_flagged(self):
        # Importing a standard middleware under an alias is still the stack's own
        # middleware, so `add_middleware(CORS)` must stay silent.
        src = (
            "from starlette.middleware.cors import CORSMiddleware as CORS\n"
            "def wire(app):\n"
            "    app.add_middleware(CORS)\n"
        )
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_add_middleware_with_a_computed_argument_is_ignored(self):
        # A middleware built by a call has no static name to check, so it is
        # neither matched against the framework set nor flagged.
        src = "def wire(app):\n    app.add_middleware(make_middleware())\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_own_class_aliased_like_a_standard_middleware_is_flagged(self):
        # A user's own middleware imported from their package under a name that
        # collides with a standard one is still custom. Alias resolution trusts
        # only the framework module roots, so this stays flagged.
        src = (
            "from myapp.middleware import CORSMiddleware as CORS\n"
            "def wire(app):\n"
            "    app.add_middleware(CORS)\n"
        )
        assert len(_detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_class_with_multiple_unrelated_bases_is_not_flagged(self):
        # Walking past several non-middleware bases still lands on "not custom".
        src = "class M(Foo, Bar):\n    pass\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_a_plain_class_is_not_flagged(self):
        src = "class Order:\n    async def dispatch(self):\n        return None\n"
        assert _detect_custom_middleware(trees(src), OWNS_ALL, NO_DEFAULTS) == []


class TestQueueStatusDetector:
    def test_queue_like_status_field_is_flagged(self):
        src = (
            "class Job:\n"
            "    status = String(choices=['pending', 'processing', 'done', 'failed'])\n"
        )
        findings = _detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS)
        assert len(findings) == 1
        assert findings[0].code == "OPPORTUNITY_OUTBOX"
        assert "0.14.0" in findings[0].detail

    def test_annotated_assignment_is_flagged(self):
        src = "class Job:\n    state: str = Field(choices=['queued', 'sent'])\n"
        assert len(_detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_non_queue_status_choices_are_not_flagged(self):
        # A domain `status` with business choices is not a work queue.
        src = "class User:\n    status = String(choices=['active', 'inactive'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_non_string_choice_members_are_skipped(self):
        # A non-string member in the choices list is skipped; the string queue
        # tokens still drive the match.
        src = "class Job:\n    status = String(choices=['pending', 'processing', 3])\n"
        assert len(_detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_single_queue_token_is_not_enough(self):
        # One overlapping token is too loose; a match needs at least two.
        src = "class User:\n    status = String(choices=['pending', 'approved'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_enum_choices_are_not_read(self):
        # An enum reference has no literal members to inspect, so it stays silent.
        src = "class Job:\n    status = String(choices=JobStatus)\n"
        assert _detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_non_status_field_with_queue_words_is_not_flagged(self):
        src = "class Job:\n    label = String(choices=['pending', 'done', 'failed'])\n"
        assert _detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS) == []

    def test_other_field_keywords_are_skipped_before_choices(self):
        # A field carrying more than `choices` still matches on its choices.
        src = (
            "class Job:\n"
            "    status = String(required=True, "
            "choices=['pending', 'processing', 'done'])\n"
        )
        assert len(_detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1

    def test_a_non_call_assignment_is_ignored(self):
        # A plain constant assignment beside the field is not a field at all.
        src = (
            "DEFAULT = 'pending'\n"
            "class Job:\n"
            "    status = String(choices=['pending', 'processing', 'done'])\n"
        )
        assert len(_detect_queue_status(trees(src), OWNS_ALL, NO_DEFAULTS)) == 1


@pytest.mark.no_test_domain
class TestDefaultSanitizeDetector:
    # The sanitize-default flip shipped in 0.18.0, so the detector only fires
    # once the domain is pinned there or later.
    OWNS = parse_version("0.18.0")

    # Every fixture imports the factories the way a real domain module does.
    # The detector resolves `String`/`Text` back to a Protean import, so an
    # unbound name is not a field declaration.
    IMPORT = "from protean.fields import String, Text\n"

    def _findings(self, body: str, pinned=None, domain=NO_DEFAULTS):
        return _detect_default_sanitize(
            trees(self.IMPORT + body), pinned or self.OWNS, domain
        )

    def test_unset_string_field_is_flagged(self):
        findings = self._findings("class User:\n    name = String(max_length=50)\n")
        assert len(findings) == 1
        finding = findings[0]
        assert finding.code == "SANITIZE_DEFAULT_CHANGED"
        assert finding.level == "info"
        assert "0.18.0" in finding.detail
        assert "m:3" in finding.detail

    def test_unset_text_field_is_flagged(self):
        assert len(self._findings("class Post:\n    body = Text()\n")) == 1

    def test_counts_every_unset_site(self):
        findings = self._findings(
            "class User:\n    name = String()\n    bio = Text()\n"
        )
        assert findings[0].title.startswith("2 ")

    def test_explicit_sanitize_false_is_not_flagged(self):
        # A field that declares its intent is unaffected by the flip.
        assert self._findings("class User:\n    name = String(sanitize=False)\n") == []

    def test_explicit_sanitize_true_is_not_flagged(self):
        assert self._findings("class User:\n    name = String(sanitize=True)\n") == []

    def test_choices_field_is_not_flagged(self):
        # A choices field was never sanitized, so it never relied on the default.
        body = "class User:\n    status = String(choices=['active', 'inactive'])\n"
        assert self._findings(body) == []

    def test_text_choices_field_is_not_flagged(self):
        # The choices carve-out applies to Text too, not just String.
        body = "class Post:\n    kind = Text(choices=['draft', 'published'])\n"
        assert self._findings(body) == []

    def test_kwargs_splat_is_not_flagged(self):
        # `String(**opts)` hides its keywords from a static scan; `sanitize` or
        # `choices` could be inside, so the site is skipped rather than reported
        # as a false positive.
        assert self._findings("class User:\n    name = String(**opts)\n") == []

    def test_kwargs_splat_alongside_explicit_kwargs_is_not_flagged(self):
        body = "class User:\n    name = String(max_length=50, **opts)\n"
        assert self._findings(body) == []

    def test_args_splat_is_not_flagged(self):
        # `String(*opts)` hides its positional arguments the same way, and
        # `sanitize` is positional-or-keyword, so it could be in there.
        assert self._findings("class User:\n    name = String(*opts)\n") == []

    def test_non_string_field_is_not_flagged(self):
        body = "class User:\n    age = Integer()\n    joined = DateTime()\n"
        assert self._findings(body) == []

    def test_annotation_style_declaration_is_flagged(self):
        body = "class User:\n    name: String(max_length=50)\n"
        assert len(self._findings(body)) == 1

    # -- Resolving what `String`/`Text` actually name -----------------------

    def test_module_qualified_call_is_flagged(self):
        # `fields.String(...)` reaches the same factory through the module path.
        src = (
            "from protean import fields\n"
            "class User:\n"
            "    name = fields.String(max_length=50)\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_dotted_module_import_is_flagged(self):
        src = (
            "import protean\n"
            "class User:\n"
            "    name = protean.fields.String(max_length=50)\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_aliased_import_is_flagged(self):
        # `String as StringField` is still a Protean field declaration; matching
        # on the trailing name alone would miss it.
        src = (
            "from protean.fields import String as StringField\n"
            "class User:\n"
            "    name = StringField(max_length=50)\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_aliased_text_import_is_flagged(self):
        src = (
            "from protean.fields import Text as Body\nclass Post:\n    body = Body()\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_string_from_another_library_is_not_flagged(self):
        # SQLAlchemy has a `String` too, and it is not a Protean field.
        src = (
            "from sqlalchemy import Column, String\n"
            "class UserTable:\n"
            "    name = Column(String(50))\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_unimported_local_string_is_not_flagged(self):
        # A locally defined `String` shares the name and nothing else.
        src = "def String(**kw):\n    return kw\nclass User:\n    name = String()\n"
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_later_import_shadows_an_earlier_one(self):
        # Python rebinding: the SQLAlchemy import wins, so the call is not a
        # Protean field declaration.
        src = (
            "from protean.fields import String\n"
            "from sqlalchemy import String\n"
            "class UserTable:\n"
            "    name = String(50)\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_later_protean_import_shadows_a_foreign_one(self):
        src = (
            "from sqlalchemy import String\n"
            "from protean.fields import String\n"
            "class User:\n"
            "    name = String(max_length=50)\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_an_aliased_module_import_resolves(self):
        src = (
            "import protean.fields as pf\n"
            "class User:\n"
            "    name = pf.String(max_length=50)\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_another_protean_submodule_is_not_the_field_module(self):
        # `import protean` reaches `protean.fields.String`, but a `String` in
        # some other Protean submodule is a different symbol.
        src = (
            "import protean\n"
            "class User:\n"
            "    name = protean.other.String(max_length=50)\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_an_unrelated_module_attribute_call_is_not_flagged(self):
        src = "import sqlalchemy\nclass UserTable:\n    name = sqlalchemy.String(50)\n"
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    # -- Names rebound by something other than an import ---------------------

    def test_a_reassigned_name_is_no_longer_the_factory(self):
        # `String = make_factory()` rebinds the name, so the later call is not
        # Protean's factory.
        src = (
            "from protean.fields import String\n"
            "String = make_factory()\n"
            "class User:\n"
            "    name = String()\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_declaration_before_the_reassignment_is_still_flagged(self):
        src = (
            "from protean.fields import String\n"
            "class User:\n"
            "    name = String(max_length=50)\n"
            "String = make_factory()\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:3" in findings[0].detail

    def test_a_parameter_shadows_the_factory_inside_the_function(self):
        # The scan cannot know what the caller passes.
        src = (
            "from protean.fields import String\n"
            "def build(String):\n"
            "    return String()\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_parameter_does_not_shadow_outside_the_function(self):
        src = (
            "from protean.fields import String\n"
            "def build(String):\n"
            "    return String()\n"
            "class User:\n"
            "    name = String(max_length=50)\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:5" in findings[0].detail

    def test_a_loop_target_rebinds_the_name(self):
        src = (
            "from protean.fields import String\n"
            "for String in factories:\n"
            "    pass\n"
            "class User:\n"
            "    name = String()\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_foreign_star_import_drops_the_binding(self):
        # A star import from elsewhere may overwrite `String`, and the scan
        # cannot tell, so it stops claiming the name is Protean's.
        src = (
            "from protean.fields import String\n"
            "from vendor.types import *\n"
            "class User:\n"
            "    name = String()\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_declaration_before_a_foreign_star_import_is_still_flagged(self):
        src = (
            "from protean.fields import String\n"
            "class User:\n"
            "    name = String(max_length=50)\n"
            "from vendor.types import *\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:3" in findings[0].detail

    def test_a_function_named_like_the_factory_rebinds_it(self):
        src = (
            "from protean.fields import String\n"
            "def String(**kw):\n"
            "    return kw\n"
            "class User:\n"
            "    name = String()\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    # -- Attribute chains the scan cannot resolve ----------------------------

    def test_a_call_rooted_attribute_chain_is_not_flagged(self):
        # `get_fields().String(...)` has a call, not a name, at the root of the
        # chain, so there is no import binding to resolve it against.
        src = (
            "from protean import fields\n"
            "class User:\n"
            "    name = get_fields().String(max_length=50)\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_an_untracked_attribute_call_is_not_flagged(self):
        # `fields.Integer()` reaches the field module but is not a tracked
        # symbol.
        src = "from protean import fields\nclass User:\n    age = fields.Integer()\n"
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_container_with_a_plain_type_argument_is_handled(self):
        # `List(int)` passes a name, not a call, so there is no inner spec to
        # hold back.
        src = (
            "from protean.fields import List, String\n"
            "class Post:\n"
            "    counts = List(int)\n"
            "    name = String(max_length=50)\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:4" in findings[0].detail

    # -- Lexical scope --------------------------------------------------------

    def test_a_helper_local_import_does_not_shadow_the_module(self):
        # The reported failure: a helper that imports SQLAlchemy's String must
        # not make the real module-level field declaration disappear from the
        # checklist.
        src = (
            "from protean.fields import String\n"
            "class User:\n"
            "    name = String(max_length=50)\n"
            "def build_table():\n"
            "    from sqlalchemy import String\n"
            "    return String(50)\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:3" in findings[0].detail
        assert "m:6" not in findings[0].detail

    def test_a_helper_local_import_shadows_inside_that_helper(self):
        src = (
            "from protean.fields import String\n"
            "def build_table():\n"
            "    from sqlalchemy import String\n"
            "    return String(50)\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_helper_local_protean_import_is_resolved(self):
        # The reverse: a field declared inside a function whose own import
        # brings in the Protean factory is still a site.
        src = (
            "def make_vo():\n"
            "    from protean.fields import String\n"
            "    class VO:\n"
            "        name = String(max_length=50)\n"
            "    return VO\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:4" in findings[0].detail

    def test_a_helper_local_import_does_not_leak_to_a_sibling(self):
        # Two helpers, only one of which imports the factory.
        src = (
            "def a():\n"
            "    from protean.fields import String\n"
            "    return String()\n"
            "def b():\n"
            "    return String()\n"
        )
        findings = _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)
        assert len(findings) == 1
        assert "m:3" in findings[0].detail

    def test_a_class_body_sees_the_module_binding(self):
        # The ordinary shape: the class body is a nested scope, and it inherits
        # what the module bound above it.
        src = (
            "from protean.fields import String\n"
            "class Outer:\n"
            "    class Inner:\n"
            "        name = String()\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_an_import_below_a_declaration_does_not_apply_above_it(self):
        # Statements are read in order, so a name resolves to what it held at
        # that point.
        src = (
            "class UserTable:\n"
            "    name = String(50)\n"
            "from protean.fields import String\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    # -- Explicit opt-ins passed positionally --------------------------------

    def test_positional_sanitize_on_text_is_not_flagged(self):
        # `sanitize` is the first positional parameter of `Text`, so `Text(True)`
        # is an explicit opt-in, not a field relying on the old default.
        assert self._findings("class Post:\n    body = Text(True)\n") == []

    def test_positional_sanitize_on_string_is_not_flagged(self):
        # `String(max_length, min_length, sanitize)` — the third positional slot.
        body = "class User:\n    name = String(255, None, True)\n"
        assert self._findings(body) == []

    def test_positional_args_short_of_sanitize_are_still_flagged(self):
        # Two positional arguments stop before the `sanitize` slot, so the field
        # still left it unset.
        assert len(self._findings("class User:\n    name = String(255, 2)\n")) == 1

    # -- Container content specs ---------------------------------------------

    def test_string_inside_a_list_content_spec_is_not_flagged(self):
        # `List` reads the inner spec's type and choices and never attaches its
        # sanitization validator, so the inner `String` was not sanitized before
        # the flip either.
        src = (
            "from protean.fields import List, String\n"
            "class Post:\n"
            "    tags = List(String(max_length=50))\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_string_as_a_keyword_content_spec_is_not_flagged(self):
        src = (
            "from protean.fields import List, String\n"
            "class Post:\n"
            "    tags = List(content_type=String(max_length=50))\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_text_inside_a_dict_value_spec_is_not_flagged(self):
        src = (
            "from protean.fields import Dict, Text\n"
            "class Post:\n"
            "    meta = Dict(value_type=Text())\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_an_aliased_container_still_skips_its_content_spec(self):
        # The container is resolved the same way the field factories are, so an
        # aliased `List` does not turn its inner spec into a false positive.
        src = (
            "from protean.fields import List as StringList, String\n"
            "class Post:\n"
            "    tags = StringList(String(max_length=50))\n"
        )
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    def test_a_container_from_elsewhere_does_not_shield_its_argument(self):
        # A non-Protean `List` is not a Protean container, so a Protean `String`
        # inside it is still a field declaration.
        src = (
            "from typing import List\n"
            "from protean.fields import String\n"
            "class Post:\n"
            "    tags = List(String(max_length=50))\n"
        )
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    # -- The domain's own default --------------------------------------------

    def test_domain_default_true_suppresses_the_finding(self):
        # With `[field_defaults] sanitize = true` the domain already opted every
        # unset field back into the old behavior, so nothing changed for them.
        domain = _StubDomain({"field_defaults": {"sanitize": True}})
        body = "class User:\n    name = String(max_length=50)\n"
        assert self._findings(body, domain=domain) == []

    def test_domain_default_true_as_a_string_suppresses_the_finding(self):
        # Env-var interpolation yields strings; they are read the same way the
        # field layer reads them.
        domain = _StubDomain({"field_defaults": {"sanitize": "true"}})
        body = "class User:\n    name = String(max_length=50)\n"
        assert self._findings(body, domain=domain) == []

    def test_domain_default_false_leaves_the_finding(self):
        domain = _StubDomain({"field_defaults": {"sanitize": False}})
        body = "class User:\n    name = String(max_length=50)\n"
        assert len(self._findings(body, domain=domain)) == 1

    def test_a_malformed_domain_default_raises_rather_than_guessing(self):
        # A config mutated to a non-mapping must not be read as "sanitize is
        # off". The detector cannot tell whether these sites need migrating
        # without knowing the default, so it raises; `run_opportunity_checks`
        # turns that into a CHECK_FAILED that says the report is incomplete.
        domain = _StubDomain({"field_defaults": False})
        body = "class User:\n    name = String(max_length=50)\n"
        with pytest.raises(TypeError):
            self._findings(body, domain=domain)

    def test_an_unrecognized_domain_default_raises(self):
        domain = _StubDomain({"field_defaults": {"sanitize": "maybe"}})
        body = "class User:\n    name = String(max_length=50)\n"
        with pytest.raises(ConfigurationError):
            self._findings(body, domain=domain)

    # -- `None` means unset, not declared ------------------------------------

    def test_explicit_sanitize_none_is_still_flagged(self):
        # `FieldSpec` reads `sanitize=None` exactly as it reads an absent
        # kwarg, so the field did rely on the old default.
        assert (
            len(self._findings("class User:\n    name = String(sanitize=None)\n")) == 1
        )

    def test_positional_sanitize_none_is_still_flagged(self):
        assert len(self._findings("class Post:\n    body = Text(None)\n")) == 1

    def test_choices_none_is_still_flagged(self):
        # `choices=None` is not a choices field: the validator reads
        # `self.choices is None` to mean no constraint, so the field was
        # sanitized under the old default.
        assert (
            len(self._findings("class User:\n    name = String(choices=None)\n")) == 1
        )

    def test_an_unreadable_sanitize_expression_is_skipped(self):
        # A name the scan cannot resolve could be either value, so the site is
        # skipped rather than reported as a false positive.
        assert self._findings("class User:\n    name = String(sanitize=FLAG)\n") == []

    # -- Star imports ---------------------------------------------------------

    def test_a_star_import_still_resolves_the_factories(self):
        # `from protean.fields import *` binds `String`/`Text` under their own
        # names. Leaving them unbound would drop the whole module from the
        # checklist without saying so.
        src = "from protean.fields import *\nclass User:\n    name = String()\n"
        assert len(_detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS)) == 1

    def test_a_star_import_from_elsewhere_does_not_bind(self):
        src = "from sqlalchemy import *\nclass User:\n    name = String()\n"
        assert _detect_default_sanitize(trees(src), self.OWNS, NO_DEFAULTS) == []

    # -- The report is a checklist -------------------------------------------

    def test_every_site_is_listed_not_summarised(self):
        # More than ten sites: the detail is the migration checklist, so a site
        # left off it is a site nobody reviews.
        body = "class User:\n" + "".join(f"    f{i} = String()\n" for i in range(12))
        findings = self._findings(body)
        assert findings[0].title.startswith("12 ")
        assert "more)" not in findings[0].detail
        for line in range(3, 15):
            assert f"m:{line}" in findings[0].detail


class TestVersionGate:
    _SRC = (
        "from sqlalchemy import text\n"
        "def q(s):\n"
        "    return s.execute(text('SELECT 1'))\n"
    )

    def test_pinned_below_the_release_suppresses_the_finding(self):
        # The query API arrived in 0.16.0; a domain pinned to 0.15.0 does not own
        # it yet, so there is nothing to claim.
        assert (
            _detect_raw_sql(trees(self._SRC), parse_version("0.15.0"), NO_DEFAULTS)
            == []
        )

    def test_pinned_at_the_release_surfaces_the_finding(self):
        assert (
            len(_detect_raw_sql(trees(self._SRC), parse_version("0.16.0"), NO_DEFAULTS))
            == 1
        )

    def test_pinned_above_the_release_surfaces_the_finding(self):
        assert (
            len(_detect_raw_sql(trees(self._SRC), parse_version("0.17.2"), NO_DEFAULTS))
            == 1
        )

    def test_middleware_gate_suppresses_below_its_release(self):
        # DomainContextMiddleware arrived in 0.15.0.
        src = (
            "from starlette.middleware.base import BaseHTTPMiddleware\n"
            "class M(BaseHTTPMiddleware):\n"
            "    pass\n"
        )
        assert (
            _detect_custom_middleware(trees(src), parse_version("0.14.0"), NO_DEFAULTS)
            == []
        )

    def test_outbox_gate_suppresses_below_its_release(self):
        # The outbox arrived in 0.14.0.
        src = "class Job:\n    status = String(choices=['pending', 'done', 'failed'])\n"
        assert (
            _detect_queue_status(trees(src), parse_version("0.13.1"), NO_DEFAULTS) == []
        )

    _SANITIZE_SRC = (
        "from protean.fields import String\n"
        "class User:\n"
        "    name = String(max_length=50)\n"
    )

    def test_sanitize_gate_suppresses_below_its_release(self):
        # The sanitize-default flip shipped in 0.18.0; a domain pinned to 0.17.0
        # still has the old default, so there is nothing to migrate yet.
        findings = _detect_default_sanitize(
            trees(self._SANITIZE_SRC), parse_version("0.17.0"), NO_DEFAULTS
        )
        assert findings == []

    def test_sanitize_gate_surfaces_at_its_release(self):
        findings = _detect_default_sanitize(
            trees(self._SANITIZE_SRC), parse_version("0.18.0"), NO_DEFAULTS
        )
        assert len(findings) == 1


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
        def boom(trees, pinned, domain):
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
