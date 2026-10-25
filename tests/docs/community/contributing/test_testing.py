"""Check the examples on docs/community/contributing/testing.md.

``001.py`` is a test that uses the ``test_domain`` fixture from
``tests/conftest.py``. The page says that fixture gives each test a fresh
domain named ``Test`` with test configuration, so the example test is called
here with the real fixture. ``002.py`` holds the ``place_order`` section the
page uses to show how a page includes code from ``docs_src``.

``003.py`` to ``009.py`` are the good examples in "Writing tests that last",
one file per rule that shows a runnable test. Each is a pytest module, so
each runs in a child pytest process with ``run_example_tests``, which collects
and runs its tests the way pytest does for a contributor.
The exact ``passed`` count catches an example whose tests stop being collected.

The last tests read the page itself. They check the section's place and
headings, and the two other places on the page that link to its rules.
"""

import pytest

from protean import Domain
from protean.exceptions import ValidationError
from protean.utils.reflection import declared_fields
from tests.docs.support import (
    DOCS,
    load_example,
    outcome_counts,
    run_example_tests,
)


@pytest.fixture
def fixture_example():
    return load_example("community/contributing/testing/001.py")


def test_example_test_passes_with_the_test_domain_fixture(fixture_example, test_domain):
    fixture_example.test_domain_initialization(test_domain)


@pytest.mark.no_test_domain
def test_example_test_fails_with_another_domain(fixture_example):
    with pytest.raises(AssertionError):
        fixture_example.test_domain_initialization(Domain(name="Other"))


@pytest.mark.no_test_domain
def test_example_test_fails_with_a_test_domain_without_test_config(fixture_example):
    domain = Domain(name="Test")
    domain.config["testing"] = False

    with pytest.raises(AssertionError):
        fixture_example.test_domain_initialization(domain)


@pytest.fixture
def place_order_example():
    module = load_example("community/contributing/testing/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.mark.no_test_domain
def test_place_order_targets_the_order_aggregate(place_order_example):
    assert place_order_example.PlaceOrder.meta_.part_of is place_order_example.Order


@pytest.mark.no_test_domain
def test_place_order_requires_an_order_id(place_order_example):
    with pytest.raises(ValidationError, match="order_id.*is required"):
        place_order_example.PlaceOrder()

    assert place_order_example.PlaceOrder(order_id="o-1").order_id == "o-1"


@pytest.mark.no_test_domain
def test_order_declares_a_status_field(place_order_example):
    assert set(declared_fields(place_order_example.Order)) == {"id", "status"}


def _assert_passed(result, count):
    assert result.returncode == 0, result.stdout + result.stderr
    assert outcome_counts(result) == {"passed": count}


@pytest.mark.no_test_domain
def test_public_api_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/003.py"), 2)


@pytest.mark.no_test_domain
def test_one_behaviour_per_test_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/004.py"), 3)


@pytest.mark.no_test_domain
def test_exact_value_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/005.py"), 1)


@pytest.mark.no_test_domain
def test_parametrize_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/006.py"), 4)


@pytest.mark.no_test_domain
def test_mock_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/007.py"), 1)


@pytest.mark.no_test_domain
def test_recorded_time_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/008.py"), 3)


@pytest.mark.no_test_domain
def test_property_example_passes():
    _assert_passed(run_example_tests("community/contributing/testing/009.py"), 1)


PAGE = DOCS / "community/contributing/testing.md"


def _page_lines():
    return PAGE.read_text(encoding="utf-8").splitlines()


def _section(lines, heading, level="##"):
    start = lines.index(heading)
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(level + " ")),
        len(lines),
    )
    return lines[start + 1 : end]


def test_the_section_sits_between_tests_organization_and_important_fixtures():
    sections = [line for line in _page_lines() if line.startswith("## ")]

    position = sections.index("## Writing tests that last")

    assert sections.count("## Writing tests that last") == 1
    assert sections[position - 1] == "## Tests Organization"
    assert sections[position + 1] == "## Important Fixtures"


def test_the_section_has_one_heading_per_rule_in_order():
    section = _section(_page_lines(), "## Writing tests that last")

    assert [line for line in section if line.startswith("###")] == [
        "### Test behaviour through the public API",
        "### Test one behaviour per test and name it for that behaviour",
        "### Assert the exact value",
        "### Keep `if` and `for` out of the test body",
        "### Mock only an external service, the clock, or a failure you cannot cause",
        "### Read the recorded time instead of racing a sleep",
        "### Extend an existing test before writing a new one",
        "### Do not write a test only to reach a line",
        "### Delete a test when the evidence says it adds nothing",
        "### Prefer one property test to a long list of examples",
    ]


def test_the_coverage_constraints_link_the_rule_on_reaching_a_line():
    constraints = "\n".join(_section(_page_lines(), "### Constraints", "###"))

    assert "add tests to cover" not in constraints
    assert "(#do-not-write-a-test-only-to-reach-a-line)" in constraints


def test_the_flaky_marker_links_the_rule_on_recorded_time():
    lines = _page_lines()
    start = next(i for i, line in enumerate(lines) if line.startswith("- `flaky`:"))
    bullet = []
    for line in lines[start:]:
        if bullet and not line.startswith("  "):
            break
        bullet.append(line)

    text = " ".join(bullet)
    assert "CI suite still execute them" in text
    assert "(#read-the-recorded-time-instead-of-racing-a-sleep)" in text
