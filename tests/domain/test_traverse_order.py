"""Domain traversal loads modules in sorted order.

``os.listdir`` returns directory entries in an order that depends on the
filesystem. Anything a module registers as a side effect of being loaded,
such as an enricher, would then run, and appear in the IR, in a different
order on different machines.
"""

import sys

import pytest

from protean.domain import Domain

# Enough names that a filesystem returning them sorted by chance is unlikely.
MODULE_NAMES = [
    "zeta",
    "alpha",
    "mid",
    "beta",
    "omega",
    "delta",
    "kappa",
    "gamma",
    "theta",
    "epsilon",
]

ENRICHER_MODULE = """\
from protean.utils.globals import current_domain


def enrich(aggregate):
    pass


current_domain.register_aggregate_enricher(enrich)
"""


@pytest.fixture
def domain_dir(tmp_path):
    root = tmp_path / "traverse_order_domain"
    root.mkdir()
    (root / "domain.py").write_text(
        "from protean import Domain\ndomain = Domain()\n", encoding="utf-8"
    )
    for name in MODULE_NAMES:
        (root / f"{name}.py").write_text(ENRICHER_MODULE, encoding="utf-8")
    for sub in ("zsub", "asub"):
        (root / sub).mkdir()
        (root / sub / "hooks.py").write_text(ENRICHER_MODULE, encoding="utf-8")

    yield root

    for key in list(sys.modules):
        if key.startswith("traverse_order_domain"):
            del sys.modules[key]


@pytest.mark.no_test_domain
def test_enrichers_register_in_sorted_module_order(domain_dir):
    domain = Domain(root_path=str(domain_dir), name="TraverseOrder")
    with domain.domain_context():
        domain._traverse()

    prefix = "traverse_order_domain."
    modules = [fn.__module__ for fn in domain._aggregate_enrichers]
    assert modules == [prefix + name for name in sorted(MODULE_NAMES)] + [
        prefix + "asub.hooks",
        prefix + "zsub.hooks",
    ]
