"""Upgrade checks for the ADR-0027 transaction change.

These rules read the domain's source, so the tests drive the AST helpers over
representative snippets rather than standing up a domain per case. The
false-positive cases matter at least as much as the positive ones: a check that
fires on `repository_for(Order).get(id)` inside a Unit of Work would fire on
almost every correct handler, and people would learn to ignore it.
"""

from __future__ import annotations

import ast
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest

from protean.upgrade import _check_unit_of_work_transaction
from protean.upgrade_uow import (
    _external_io_in,
    _http_names,
    _lexically_nested,
    _uow_withs,
    scan_domain_source,
)


def parse(src: str) -> ast.Module:
    return ast.parse(src)


def io_sites(src: str) -> list[str]:
    """Labels of external-I/O calls found inside Unit of Work blocks."""
    tree = parse(src)
    names = _http_names(tree)
    return [
        label
        for block in _uow_withs(tree)
        for label, _ in _external_io_in(block, names)
    ]


class TestFindingUnitOfWorkBlocks:
    def test_finds_plain_block(self):
        assert len(_uow_withs(parse("with UnitOfWork():\n    pass"))) == 1

    def test_finds_qualified_block(self):
        assert len(_uow_withs(parse("with protean.UnitOfWork():\n    pass"))) == 1

    def test_finds_async_block(self):
        src = "async def f():\n    async with UnitOfWork():\n        pass"
        assert len(_uow_withs(parse(src))) == 1

    def test_ignores_other_context_managers(self):
        assert _uow_withs(parse("with open('f'):\n    pass")) == []


class TestNestedDetection:
    def test_detects_direct_nesting(self):
        src = "with UnitOfWork():\n    with UnitOfWork():\n        pass"
        assert len(_lexically_nested(parse(src))) == 1

    def test_detects_nesting_behind_a_branch(self):
        src = (
            "with UnitOfWork():\n"
            "    if flag:\n"
            "        with UnitOfWork():\n"
            "            pass\n"
        )
        assert len(_lexically_nested(parse(src))) == 1

    def test_sequential_blocks_are_not_nested(self):
        src = "with UnitOfWork():\n    pass\nwith UnitOfWork():\n    pass"
        assert _lexically_nested(parse(src)) == []

    def test_reports_the_inner_line_not_the_outer(self):
        src = "with UnitOfWork():\n    x = 1\n    with UnitOfWork():\n        pass"
        assert _lexically_nested(parse(src)) == [3]


class TestExternalIoDetection:
    def test_module_level_http_call(self):
        src = "import httpx\nwith UnitOfWork():\n    httpx.post(url, json=payload)\n"
        assert io_sites(src) == ["httpx.post()"]

    def test_client_stored_on_self(self):
        """The webhook-dispatcher shape: client built once, used later."""
        src = (
            "import httpx\n"
            "class D:\n"
            "    def __init__(self):\n"
            "        self._client = httpx.Client()\n"
            "    def run(self):\n"
            "        with UnitOfWork():\n"
            "            self._client.post(url)\n"
        )
        assert io_sites(src) == ["self._client.post()"]

    def test_aliased_import(self):
        src = "import requests as rq\nwith UnitOfWork():\n    rq.get(url)\n"
        assert io_sites(src) == ["rq.get()"]

    def test_from_import(self):
        src = (
            "from urllib.request import urlopen\nwith UnitOfWork():\n    urlopen(url)\n"
        )
        assert io_sites(src) == ["urlopen()"]

    def test_broker_publish(self):
        src = "with UnitOfWork():\n    broker.publish(stream, message)\n"
        assert io_sites(src) == ["publish()"]

    def test_email_send(self):
        src = "with UnitOfWork():\n    mailer.send_email(to, body)\n"
        assert io_sites(src) == ["send_email()"]

    def test_reports_every_call_not_just_the_first(self):
        src = "import httpx\nwith UnitOfWork():\n    httpx.post(a)\n    httpx.post(b)\n"
        assert len(io_sites(src)) == 2


class TestDoesNotFireOnCorrectCode:
    """The cases that would make this rule noise rather than signal."""

    def test_repository_get_is_not_http(self):
        src = "with UnitOfWork():\n    order = repository_for(Order).get(order_id)\n"
        assert io_sites(src) == []

    def test_repository_add_and_get_on_a_variable(self):
        src = (
            "with UnitOfWork():\n"
            "    repo = repository_for(Order)\n"
            "    order = repo.get(order_id)\n"
            "    repo.add(order)\n"
        )
        assert io_sites(src) == []

    def test_http_verb_without_an_http_import(self):
        """`self._store.get(...)` is not I/O just because it is named `get`."""
        src = "with UnitOfWork():\n    self._store.get(key)\n"
        assert io_sites(src) == []

    def test_http_call_outside_the_block_is_ignored(self):
        src = (
            "import httpx\n"
            "with UnitOfWork():\n"
            "    repository_for(Order).add(order)\n"
            "httpx.post(url)\n"
        )
        assert io_sites(src) == []

    def test_dict_get_is_not_http(self):
        src = "import httpx\nwith UnitOfWork():\n    value = payload.get('key')\n"
        assert io_sites(src) == []

    def test_no_uow_means_nothing_to_report(self):
        src = "import httpx\nhttpx.post(url)\n"
        assert io_sites(src) == []

    @pytest.mark.parametrize(
        "helper", ["urlencode", "urljoin", "quote", "unquote", "urlparse"]
    )
    def test_url_helpers_are_not_io(self, helper):
        """`urllib` exports plenty that never touches the network.

        These come from a module in the HTTP list, so a rule that flagged any
        imported name would flag them, and they are common inside a Unit of
        Work while building a request to send *after* it.
        """
        src = (
            f"from urllib.parse import {helper}\n"
            "with UnitOfWork():\n"
            f"    value = {helper}(payload)\n"
        )
        assert io_sites(src) == []

    def test_building_a_client_is_not_io(self):
        """A constructor only builds the client; it makes no request."""
        src = (
            "from requests import Session\n"
            "with UnitOfWork():\n"
            "    session = Session()\n"
        )
        assert io_sites(src) == []

    def test_a_verb_imported_from_an_http_library_is_still_io(self):
        """The narrowing must not lose the case it was protecting."""
        src = "from httpx import get\nwith UnitOfWork():\n    get(url)\n"
        assert io_sites(src) == ["get()"]


class TestNestedBlocksAreNotDoubleCounted:
    def test_inner_block_calls_belong_to_the_inner_block(self):
        src = (
            "import httpx\n"
            "with UnitOfWork():\n"
            "    with UnitOfWork():\n"
            "        httpx.post(url)\n"
        )
        # Two blocks are found, but the call is attributed once: to the inner
        # block, not to both.
        assert io_sites(src) == ["httpx.post()"]


class TestHttpNameTracking:
    def test_no_http_import_means_no_tracked_names(self):
        assert _http_names(parse("import json\nx = json.loads(s)\n")) == set()

    def test_import_seeds_the_name(self):
        assert "httpx" in _http_names(parse("import httpx\n"))

    def test_assignment_propagates(self):
        tree = parse("import requests\ns = requests.Session()\n")
        assert "s" in _http_names(tree)

    @pytest.mark.parametrize("module", ["httpx", "requests", "urllib3", "aiohttp"])
    def test_each_known_library(self, module):
        assert module in _http_names(parse(f"import {module}\n"))


class TestFindingsFromAScannedDomain:
    """The reporting layer, driven by patching the scan it consumes.

    The scan itself is covered above against real source; this pins the
    finding codes, levels, and the one branch that is easy to get wrong: a
    domain with Unit of Work blocks but no lexical nesting still gets a note,
    because indirect nesting cannot be seen statically.
    """

    def _findings(self, nested, io_sites, total):
        with patch(
            "protean.upgrade.scan_domain_source",
            return_value=(nested, io_sites, total),
        ):
            return {f.code: f for f in _check_unit_of_work_transaction(MagicMock())}

    def test_clean_domain_reports_nothing(self):
        assert self._findings([], [], 0) == {}

    def test_nesting_is_a_warning(self):
        found = self._findings(["m:3"], [], 2)
        assert found["NESTED_UNIT_OF_WORK"].level == "warning"
        assert "m:3" in found["NESTED_UNIT_OF_WORK"].detail
        # The review note is for domains with *no* nesting found.
        assert "UNIT_OF_WORK_NESTING_REVIEW" not in found

    def test_blocks_without_nesting_get_the_review_note(self):
        found = self._findings([], [], 7)
        note = found["UNIT_OF_WORK_NESTING_REVIEW"]
        assert note.level == "info"
        assert "7 Unit of Work block(s)" in note.title

    def test_io_is_a_warning_and_is_independent_of_nesting(self):
        found = self._findings([], ["m:9 (httpx.post())"], 1)
        assert found["IO_INSIDE_UNIT_OF_WORK"].level == "warning"
        assert "httpx.post()" in found["IO_INSIDE_UNIT_OF_WORK"].detail

    def test_both_hazards_are_reported_together(self):
        found = self._findings(["m:3"], ["m:9 (publish())"], 4)
        assert {"NESTED_UNIT_OF_WORK", "IO_INSIDE_UNIT_OF_WORK"} <= set(found)

    def test_long_lists_are_truncated_with_a_count(self):
        found = self._findings([f"m:{i}" for i in range(25)], [], 25)
        assert "(and 15 more)" in found["NESTED_UNIT_OF_WORK"].detail


class TestHelperEdges:
    """Small branches that are easy to leave unexercised."""

    def test_a_non_call_context_manager_is_not_a_uow(self):
        # `with some_cm:` has an expression, not a call, as its context.
        assert _uow_withs(parse("with some_cm:\n    pass")) == []

    def test_a_subscript_call_is_not_a_uow(self):
        # `with managers[0]():` is a Call whose func is neither Name nor
        # Attribute, so there is no name to compare.
        assert _uow_withs(parse("with managers[0]():\n    pass")) == []

    def test_assignment_from_an_unnamed_source_is_skipped(self):
        # `c = f()[0]` has no root name to trace, so it must not be tracked.
        tree = parse("import httpx\nc = make()[0]\n")
        assert "c" not in _http_names(tree)

    def test_a_bare_call_to_an_imported_client_is_io(self):
        src = (
            "from httpx import get\n"
            "with UnitOfWork():\n"
            "    get('https://example.test')\n"
        )
        assert io_sites(src) == ["get()"]


@pytest.mark.no_test_domain
class TestScanAgainstRealSource:
    """Drive the scan over a real domain package on disk.

    The helper tests above work on parsed snippets and the finding tests patch
    the scan out, so without this the function that actually walks a domain's
    modules would never run.
    """

    def _domain_at(self, tmp_path, body: str):
        pkg = tmp_path / "scanapp"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "domain.py").write_text(body)
        sys.path.insert(0, str(tmp_path))
        try:
            module = importlib.import_module("scanapp.domain")
            module.domain.init(traverse=False)
            return module.domain
        finally:
            sys.path.remove(str(tmp_path))

    def teardown_method(self):
        for name in [m for m in sys.modules if m.startswith("scanapp")]:
            del sys.modules[name]

    def test_scan_finds_both_hazards_in_real_source(self, tmp_path):
        domain = self._domain_at(
            tmp_path,
            "import httpx\n"
            "from protean import Domain, UnitOfWork\n"
            "from protean.fields import String\n"
            "\n"
            "domain = Domain(name='Scan')\n"
            "\n"
            "@domain.aggregate\n"
            "class Order:\n"
            "    status = String()\n"
            "\n"
            "def handle(order_id):\n"
            "    with UnitOfWork():\n"
            "        order = domain.repository_for(Order).get(order_id)\n"
            "        httpx.post('https://hook', json={'id': order_id})\n"
            "        with UnitOfWork():\n"
            "            domain.repository_for(Order).add(order)\n",
        )

        with domain.domain_context():
            nested, io_sites_found, total = scan_domain_source(domain)

        assert total == 2, "both the outer and inner blocks should be counted"
        assert len(nested) == 1
        assert len(io_sites_found) == 1
        assert "httpx.post()" in io_sites_found[0]
        # The repository call sits beside the HTTP call and must not be flagged.
        assert not any("get()" in s for s in io_sites_found)

    def test_scan_of_a_clean_domain_reports_nothing(self, tmp_path):
        domain = self._domain_at(
            tmp_path,
            "from protean import Domain, UnitOfWork\n"
            "from protean.fields import String\n"
            "\n"
            "domain = Domain(name='Scan')\n"
            "\n"
            "@domain.aggregate\n"
            "class Order:\n"
            "    status = String()\n"
            "\n"
            "def handle(order_id):\n"
            "    with UnitOfWork():\n"
            "        domain.repository_for(Order).get(order_id)\n",
        )

        with domain.domain_context():
            nested, io_sites_found, total = scan_domain_source(domain)

        assert (nested, io_sites_found) == ([], [])
        assert total == 1
