"""Plugin fixtures checked under ``mypy --strict``.

Each fixture states its expectations inline. A line ending in ``# R: <type>``
must produce that revealed type, and a line ending in ``# E: <code>`` must
produce an error with that code. Any other error, or any reveal without a
marker, fails the fixture. ``strict_sample.py`` is a small domain in the
canonical typed-annotation style that must type-check with no errors at all.

All fixtures go through one mypy run, cached for the module.
"""

import importlib.util
import re
import sys
from functools import lru_cache
from pathlib import Path

import pytest
from mypy import api as mypy_api

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_STRICT_CONFIG = Path(__file__).parent / "mypy_plugin_strict_config.ini"

_STRICT_FIXTURES = [
    "strict_typed_annotation.py",
    "strict_annotation_only.py",
    "strict_mismatch.py",
    "strict_dict_annotation.py",
    "strict_base_class_params.py",
    "strict_element_types.py",
    "strict_upcaster.py",
    "strict_handle_any.py",
    "strict_queryset_self.py",
    "strict_sample.py",
]

_OUTPUT_LINE = re.compile(
    r"^(?P<file>[^:]+\.py):(?P<line>\d+): (?P<kind>error|note): (?P<message>.*)$"
)
_REVEAL = re.compile(r'Revealed type is "(?P<type>.*)"$')
_ERROR_CODE = re.compile(r"\[(?P<code>[a-z-]+)\]$")
_EXPECT_REVEAL = re.compile(r"# R: (?P<type>.+)$")
_EXPECT_ERROR = re.compile(r"# E: (?P<code>[a-z-]+)$")
# mypy qualifies class names with their module; the expectations use the bare
# class name so they read the way the fixture is written.
_MODULE_PREFIX = re.compile(r"\b(?:[a-z_][a-z0-9_]*\.)+(?=[A-Za-z_])")


def _normalize(revealed: str) -> str:
    return _MODULE_PREFIX.sub("", revealed)


Findings = dict[int, list[str]]


@lru_cache(maxsize=1)
def _run_mypy() -> dict[str, tuple[Findings, Findings]]:
    """Run mypy strict over every fixture; return (reveals, errors) per fixture."""
    result = mypy_api.run(
        [
            "--config-file",
            str(_STRICT_CONFIG),
            "--no-incremental",
            "--show-error-codes",
            "--no-error-summary",
            "--hide-error-context",
            *(str(FIXTURES_DIR / name) for name in _STRICT_FIXTURES),
        ]
    )
    stdout, stderr, status = result
    # 0 is a clean run and 1 means mypy reported errors. Anything else is a
    # crash or a bad invocation, which would otherwise read as no findings.
    assert status in (0, 1), f"mypy exited with {status}:\n{stderr}{stdout}"
    findings: dict[str, tuple[Findings, Findings]] = {
        name: ({}, {}) for name in _STRICT_FIXTURES
    }
    for raw in stdout.splitlines():
        match = _OUTPUT_LINE.match(raw)
        if match is None:
            continue
        name = Path(match["file"]).name
        assert name in findings, f"mypy reported on an unexpected file: {raw}"
        reveals, errors = findings[name]
        line = int(match["line"])
        message = match["message"]
        if match["kind"] == "note":
            reveal = _REVEAL.search(message)
            if reveal is not None:
                reveals.setdefault(line, []).append(_normalize(reveal["type"]))
            continue
        code = _ERROR_CODE.search(message)
        errors.setdefault(line, []).append(code["code"] if code else message)
    return findings


def _expectations(name: str) -> tuple[Findings, Findings]:
    reveals: Findings = {}
    errors: Findings = {}
    lines = (FIXTURES_DIR / name).read_text(encoding="utf-8").splitlines()
    for number, text in enumerate(lines, start=1):
        if (reveal := _EXPECT_REVEAL.search(text)) is not None:
            reveals[number] = [reveal["type"].strip()]
        if (error := _EXPECT_ERROR.search(text)) is not None:
            errors[number] = [error["code"]]
    return reveals, errors


@pytest.mark.parametrize(
    "fixture", _STRICT_FIXTURES, ids=[name[:-3] for name in _STRICT_FIXTURES]
)
def test_fixture_matches_its_expectations(fixture: str) -> None:
    expected_reveals, expected_errors = _expectations(fixture)
    actual_reveals, actual_errors = _run_mypy()[fixture]

    assert actual_reveals == expected_reveals
    assert actual_errors == expected_errors


def test_sample_domain_declares_no_expected_errors() -> None:
    """The sample must stay clean, so it may not mark any line as an error."""
    _, expected_errors = _expectations("strict_sample.py")
    assert expected_errors == {}


def test_expectation_markers_are_found() -> None:
    """Guard against a marker typo silently turning a fixture into a no-op."""
    reveals, errors = _expectations("strict_typed_annotation.py")
    assert len(reveals) > 0
    assert len(errors) > 0


@pytest.mark.no_test_domain
def test_sample_domain_runs() -> None:
    """The sample is a working domain, so its types describe real behaviour."""
    spec = importlib.util.spec_from_file_location(
        "strict_sample", FIXTURES_DIR / "strict_sample.py"
    )
    assert spec is not None and spec.loader is not None
    sample = importlib.util.module_from_spec(spec)
    sys.modules["strict_sample"] = sample
    try:
        spec.loader.exec_module(sample)
        sample.shop.init(traverse=False)
        with sample.shop.domain_context():
            order_id = sample.place("Ada")
            order = sample.shop.repository_for(sample.Order).get(order_id)
            assert order.status == "PLACED"
            assert [item.sku for item in order.items] == ["A1"]

            summary = sample.summary_for(order_id)
            assert summary.customer == "Ada"
            assert summary.total == 10.0

            wallet = sample.Wallet.open("Ada")
            assert wallet.owner == "Ada"
            assert sample.Checkout(order, wallet)() is False
    finally:
        sys.modules.pop("strict_sample", None)


_PARENTS_MODULE = """
from protean.core.aggregate import BaseAggregate
from protean.domain import Domain
from protean.fields import Integer

domain = Domain(name="Strict")


@domain.aggregate
class Handmade:
    def __init__(self, *, left: int = 0) -> None:
        super().__init__()


@domain.aggregate(abstract=True)
class Synthesized:
    left: int | None = Integer()


class Transformed(BaseAggregate):
    left: int | None = Integer()
"""

_CHILDREN_MODULE = """
from protean.fields import Integer

from pkg.parents import Handmade, Synthesized, Transformed, domain


@domain.aggregate
class FromHandmade(Handmade):
    right: int | None = Integer()


@domain.aggregate
class FromSynthesized(Synthesized):
    right: int | None = Integer()


@domain.aggregate
class FromTransformed(Transformed):
    right: int | None = Integer()


FromHandmade(left=1)
FromHandmade(right=1)
FromSynthesized(left=1, right=2)
FromSynthesized(lft=1)
FromTransformed(left=1, right=2)
FromTransformed(lft=1)
"""


def test_parent_constructors_survive_the_cache(tmp_path: Path) -> None:
    """A parent from another module keeps its constructor kind when cached.

    The second run reads ``pkg.parents`` from mypy's cache, so the flags that
    tell a hand-written ``__init__`` from a generated one must be in it.
    """
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "parents.py").write_text(_PARENTS_MODULE, encoding="utf-8")
    children = package / "children.py"
    children.write_text(_CHILDREN_MODULE, encoding="utf-8")

    def errors() -> list[str]:
        stdout, stderr, status = mypy_api.run(
            [
                "--config-file",
                str(_STRICT_CONFIG),
                "--cache-dir",
                str(tmp_path / ".mypy_cache"),
                "--show-error-codes",
                "--no-error-summary",
                "--hide-error-context",
                str(children),
            ]
        )
        assert status in (0, 1), f"mypy exited with {status}:\n{stderr}{stdout}"
        return [
            match["message"]
            for raw in stdout.splitlines()
            if (match := _OUTPUT_LINE.match(raw)) and match["kind"] == "error"
        ]

    expected = [
        'Unexpected keyword argument "right" for "FromHandmade"  [call-arg]',
        (
            'Unexpected keyword argument "lft" for "FromSynthesized"; '
            'did you mean "left"?  [call-arg]'
        ),
        (
            'Unexpected keyword argument "lft" for "FromTransformed"; '
            'did you mean "left"?  [call-arg]'
        ),
    ]
    assert errors() == expected
    children.write_text(_CHILDREN_MODULE + "\n", encoding="utf-8")
    assert errors() == expected
