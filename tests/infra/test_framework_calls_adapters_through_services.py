"""Framework code calls an adapter through its service, never through ``_adapter``.

A service in ``protean.infra`` owns its adapter as ``_adapter``. This test
parses every module under ``src/protean`` outside ``protean/infra`` and
``protean/adapters`` and fails on a call of the form
``<expr>._adapter.<member>(...)``. Reading ``_adapter`` (an identity check,
``isinstance``) is allowed. The test does not catch an alias of ``_adapter``,
a ``getattr`` call, or a call through ``domain.event_store.store``; framework
code still reaches the adapter through ``.store`` until those callers move to
the service.
"""

import ast
from pathlib import Path

import pytest

import protean

pytestmark = pytest.mark.no_test_domain

PACKAGE_ROOT = Path(protean.__file__).parent
EXCLUDED_PACKAGES = ("infra", "adapters")


def adapter_calls(source: str) -> list[int]:
    """Return the line of every ``<expr>._adapter.<member>(...)`` call in ``source``."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_adapter"
    )


def _framework_modules() -> list[Path]:
    excluded = [PACKAGE_ROOT / name for name in EXCLUDED_PACKAGES]
    return [
        path
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if not any(path.is_relative_to(root) for root in excluded)
    ]


class TestDetector:
    def test_flags_a_member_call_through_adapter(self):
        source = "x = 1\ndomain.event_store._adapter.read('user')\n"

        assert adapter_calls(source) == [2]

    def test_allows_reading_adapter(self):
        source = "adapter = domain.event_store._adapter\nok = adapter is None\n"

        assert adapter_calls(source) == []

    def test_allows_isinstance_on_adapter(self):
        source = "isinstance(domain.event_store._adapter, MemoryEventStore)\n"

        assert adapter_calls(source) == []

    def test_allows_a_call_through_the_service(self):
        source = "domain.event_store.read('user')\n"

        assert adapter_calls(source) == []


def test_framework_modules_are_found():
    modules = _framework_modules()

    assert PACKAGE_ROOT / "domain" / "__init__.py" in modules
    assert not any(path.is_relative_to(PACKAGE_ROOT / "infra") for path in modules)
    assert not any(path.is_relative_to(PACKAGE_ROOT / "adapters") for path in modules)


def test_framework_code_calls_adapters_through_services():
    violations = [
        f"{path.relative_to(PACKAGE_ROOT.parent)}:{line}"
        for path in _framework_modules()
        for line in adapter_calls(path.read_text(encoding="utf-8"))
    ]

    assert violations == [], (
        "Call the service instead of a member on `_adapter`:\n" + "\n".join(violations)
    )
