"""Run the examples on the ``docs/concepts/protean-check/rules/`` pages.

Each page shows a flagged domain, a compliant one and a suppressed one. The
flagged domain reports the rule's code from ``domain.check()``; the other two
do not.
"""

import pytest

from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def _findings(example, code):
    report = example.domain.check(traverse=False)
    return [
        entry
        for entry in [*report["errors"], *report["diagnostics"]]
        if entry["code"] == code
    ]


# ADAPTER_CALL_IN_DOMAIN


def test_a_domain_method_that_builds_an_adapter_is_flagged():
    example = load_example(
        "concepts/protean-check/rules/adapter-call-from-domain/001.py"
    )

    findings = _findings(example, "ADAPTER_CALL_IN_DOMAIN")

    assert len(findings) == 1
    assert findings[0]["element"].endswith(".Order")
    assert "`protean.adapters.broker.inline.InlineBroker`" in findings[0]["message"]
    assert "method `provision`" in findings[0]["message"]


def test_a_self_rooted_repository_call_is_not_flagged():
    example = load_example(
        "concepts/protean-check/rules/adapter-call-from-domain/002.py"
    )

    assert example.domain.config["lint"]["check_adapter_calls"] is True
    assert _findings(example, "ADAPTER_CALL_IN_DOMAIN") == []


def test_suppress_checks_silences_the_adapter_call():
    example = load_example(
        "concepts/protean-check/rules/adapter-call-from-domain/003.py"
    )

    assert example.domain.config["lint"]["check_adapter_calls"] is True
    assert _findings(example, "ADAPTER_CALL_IN_DOMAIN") == []


# UNBOUNDED_INDEXED_STRING


def test_an_indexed_text_field_is_flagged():
    example = load_example(
        "concepts/protean-check/rules/unbounded-indexed-string/001.py"
    )

    findings = _findings(example, "UNBOUNDED_INDEXED_STRING")

    assert len(findings) == 1
    assert findings[0]["element"].endswith(".Note")
    assert "Field `body`" in findings[0]["message"]


def test_a_bounded_indexed_string_and_an_unindexed_text_are_not_flagged():
    example = load_example(
        "concepts/protean-check/rules/unbounded-indexed-string/002.py"
    )

    assert _findings(example, "UNBOUNDED_INDEXED_STRING") == []


def test_suppress_checks_silences_the_unbounded_index():
    example = load_example(
        "concepts/protean-check/rules/unbounded-indexed-string/003.py"
    )

    assert _findings(example, "UNBOUNDED_INDEXED_STRING") == []


# UNINDEXED_FILTER_PATH


def test_a_filter_on_an_unindexed_field_is_flagged_and_an_indexed_one_is_not():
    example = load_example("concepts/protean-check/rules/unindexed-filter-path/001.py")

    findings = _findings(example, "UNINDEXED_FILTER_PATH")

    assert len(findings) == 1
    assert findings[0]["element"].endswith(".Order")
    assert "Field `reference`" in findings[0]["message"]
    assert "OrderRepository.by_reference" in findings[0]["message"]


def test_indexing_the_filtered_field_clears_the_finding():
    example = load_example("concepts/protean-check/rules/unindexed-filter-path/002.py")

    assert _findings(example, "UNINDEXED_FILTER_PATH") == []


def test_suppress_checks_silences_the_unindexed_filter():
    example = load_example("concepts/protean-check/rules/unindexed-filter-path/003.py")

    assert _findings(example, "UNINDEXED_FILTER_PATH") == []
