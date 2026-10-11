"""Check the programmatic API on docs/reference/cli/data/projection.md.

The example builds a ``Banking`` domain with an ``Account`` aggregate and a
``Balances`` projection kept by ``BalancesProjector``. It opens ``acc-1`` for
Alice with two deposits (100.0 and 50.0) and ``acc-2`` for Bob, which stores
four events. Then it runs the rebuild calls the page shows. Each test loads the
example fresh, so every test gets its own domain and memory stores.
"""

import pytest

from protean.utils.projection_rebuilder import RebuildResult
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def example(capsys):
    module = load_example("reference/cli/data/projection/001.py")
    printed = capsys.readouterr().out.splitlines()
    with module.domain.domain_context():
        yield module, printed


def test_example_prints_the_events_replayed(example):
    _, printed = example

    assert printed == ["4 events replayed", "Balances: 4 events"]


def test_rebuild_all_projections_maps_each_name_to_its_result(example):
    module, _ = example

    assert module.results == {
        "Balances": RebuildResult(
            projection_name="Balances",
            projectors_processed=1,
            categories_processed=1,
            events_dispatched=4,
            events_skipped=0,
            errors=[],
        )
    }
    assert module.results["Balances"].success is True


def test_rebuild_replays_the_events_into_the_projection(example):
    module, _ = example
    repo = module.domain.repository_for(module.Balances)

    assert repo.get("acc-1").balance == 150.0
    assert repo.get("acc-2").balance == 0.0


def test_rebuild_replaces_stale_projection_data(example):
    module, _ = example
    repo = module.domain.repository_for(module.Balances)
    stale = repo.get("acc-1")
    stale.balance = 999.0
    repo.add(stale)

    result = module.domain.rebuild_projection(module.Balances)

    assert result.events_dispatched == 4
    assert repo.get("acc-1").balance == 150.0
