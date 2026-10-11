"""Check what docs/reference/init-diagnostics.md says about coded exceptions.

The example calls ``domain.view_for`` with an aggregate, which is not a
projection, and prints the attributes of the ``IncorrectUsageError`` it gets.
The page says ``rationale`` and ``fix`` come from the diagnostics registry, and
that ``code``, ``codes`` and ``location`` survive a pickle round-trip.
"""

import pickle

import pytest

from protean.exceptions import IncorrectUsageError
from protean.ir.diagnostics import DiagnosticCode, resolve
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example(capsys):
    module = load_example("reference/init-diagnostics/001.py")
    printed = capsys.readouterr().out.splitlines()
    yield module, printed


def test_example_prints_the_code_location_and_registry_text(example):
    _, printed = example
    meta = resolve(DiagnosticCode.USAGE_NOT_A_PROJECTION)

    assert printed == [
        "USAGE_NOT_A_PROJECTION",
        "['USAGE_NOT_A_PROJECTION']",
        "Domain.view_for",
        meta.rationale,
        meta.fix,
    ]


def test_view_for_an_aggregate_raises_a_coded_incorrect_usage_error(example):
    module, _ = example

    with pytest.raises(IncorrectUsageError) as info:
        module.domain.view_for(module.SomeAggregate)

    assert info.value.code == "USAGE_NOT_A_PROJECTION"
    assert info.value.location == "Domain.view_for"


def test_code_codes_and_location_survive_a_pickle_round_trip(example):
    module, _ = example
    with pytest.raises(IncorrectUsageError) as info:
        module.domain.view_for(module.SomeAggregate)

    restored = pickle.loads(pickle.dumps(info.value))

    assert restored.code == "USAGE_NOT_A_PROJECTION"
    assert restored.codes == ["USAGE_NOT_A_PROJECTION"]
    assert restored.location == "Domain.view_for"


def test_exception_raised_without_a_code_has_no_code_attributes():
    exc = IncorrectUsageError("plain message")

    assert exc.code is None
    assert exc.location is None
    assert exc.rationale is None
    assert exc.fix is None
    assert exc.codes == []
