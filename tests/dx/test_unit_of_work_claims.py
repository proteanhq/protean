"""The skills' Unit of Work pages say what the Unit of Work does.

The command-handler, application-service and repository skills describe the
Unit of Work in four places. Each place says that a Unit of Work can hold
several aggregates, that a nested one joins the outer one, and that a version
conflict re-runs a handler body up to ``1 + max_retries`` times. Each links
ADR-0027 and ADR-0031. The first group of tests reads the pages. The second
group runs the framework to show the pages are right.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from protean import Domain, dx, handle, use_case
from protean.core.unit_of_work import UnitOfWork
from protean.exceptions import ExpectedVersionError
from protean.fields import Identifier, String
from protean.utils.globals import current_uow
from protean.utils.mixins import _VERSION_RETRY_DEFAULTS

pytestmark = pytest.mark.no_test_domain

SKILLS_ROOT = Path(str(dx.pack_files())) / dx.SKILLS_DIR
ADR_DIR = Path(__file__).resolve().parents[2] / "docs" / "adr"

if not SKILLS_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the pages are read by path",
        allow_module_level=True,
    )

SITES = [
    "command-handler/references/unit-of-work.md",
    "application-service/references/unit-of-work.md",
    "repository/references/anti-patterns.md",
    "repository/references/unit-of-work.md",
]

# The pages that describe commit and rollback, and so must scope atomicity to
# providers with transactions.
ATOMICITY_SITES = [
    "command-handler/references/unit-of-work.md",
    "application-service/references/unit-of-work.md",
    "repository/references/unit-of-work.md",
]

MAX_RETRIES = _VERSION_RETRY_DEFAULTS["max_retries"]
TOTAL_RUNS = 1 + MAX_RETRIES

ADR_LINK = re.compile(r"https://docs\.proteanhq\.com/adr/(\d{4}-[a-z0-9-]+)/")


def _page(site: str) -> str:
    # Pages wrap no sentences, but join lines so a phrase split across a
    # line break still matches.
    return " ".join((SKILLS_ROOT / site).read_text(encoding="utf-8").split())


@pytest.mark.parametrize("site", SITES)
def test_the_page_links_both_adrs_and_they_exist(site):
    slugs = set(ADR_LINK.findall(_page(site)))
    numbers = {slug[:4] for slug in slugs}

    assert {"0027", "0031"} <= numbers
    for slug in slugs:
        assert (ADR_DIR / f"{slug}.md").is_file(), f"{slug} has no ADR file"


@pytest.mark.parametrize("site", SITES)
def test_the_page_states_the_total_runs_from_the_default(site):
    text = _page(site)

    assert f"`max_retries={MAX_RETRIES}`" in text
    assert f"up to {TOTAL_RUNS} times in total" in text
    assert "more times" not in text


@pytest.mark.parametrize("site", SITES)
def test_the_page_says_several_aggregates_and_nested_joins(site):
    text = _page(site)

    assert "can hold changes to several aggregates" in text
    assert "joins the outer one" in text


# The false statements the pages used to make. Each contradicts ADR-0027.
FALSE_CLAIMS = [
    "does not span",
    "nested transaction",
    "never joins",
    "does not join",
    "not written until",
]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize("claim", FALSE_CLAIMS)
def test_the_page_drops_the_false_claim(site, claim):
    assert claim not in _page(site).lower()


@pytest.mark.parametrize("site", ATOMICITY_SITES)
def test_the_page_scopes_atomicity_to_providers_with_transactions(site):
    text = _page(site)

    assert "providers with real transactions" in text
    assert "Elasticsearch has no transactions" in text
    assert "commit and rollback are not atomic" in text


# --- The framework does what the pages say ----------------------------------


def _domain():
    domain = Domain(name="UnitOfWorkClaims")
    runs: list[UnitOfWork] = []

    @domain.aggregate
    class Order:
        name = String()

    @domain.command(part_of=Order)
    class PlaceOrder:
        order_id = Identifier()

    @domain.command_handler(part_of=Order)
    class OrderCommandHandler:
        @handle(PlaceOrder)
        def place(self, command):
            runs.append(current_uow._get_current_object())
            domain.repository_for(Order).add(Order(name="placed"))
            raise ExpectedVersionError("another writer saved the order first")

    @domain.application_service(part_of=Order)
    class OrderServices:
        @use_case
        def place_via_handler(self):
            domain.process(PlaceOrder(order_id="o-1"), asynchronous=False)

        @use_case
        def conflict(self):
            runs.append(current_uow._get_current_object())
            raise ExpectedVersionError("another writer saved the order first")

    domain.init(traverse=False)
    return domain, Order, PlaceOrder, OrderServices, runs


def test_a_nested_unit_of_work_joins_the_outer_one():
    domain, Order, *_ = _domain()

    with domain.domain_context():
        with pytest.raises(RuntimeError):
            with UnitOfWork() as outer:
                with UnitOfWork():
                    assert current_uow._get_current_object() is outer
                    domain.repository_for(Order).add(Order(name="inner"))
                raise RuntimeError("the outer Unit of Work fails")

        assert domain.repository_for(Order).query.all().total == 0


def test_a_version_conflict_runs_the_handler_body_up_to_the_total():
    domain, Order, PlaceOrder, _, runs = _domain()

    with domain.domain_context():
        with pytest.raises(ExpectedVersionError):
            domain.process(PlaceOrder(order_id="o-1"), asynchronous=False)

        assert len(runs) == TOTAL_RUNS == 4
        assert len({id(uow) for uow in runs}) == TOTAL_RUNS
        assert domain.repository_for(Order).query.all().total == 0


def test_inside_an_outer_unit_of_work_every_run_joins_it():
    domain, Order, _, OrderServices, runs = _domain()

    with domain.domain_context():
        with pytest.raises(ExpectedVersionError):
            OrderServices().place_via_handler()

        assert len(runs) == TOTAL_RUNS
        assert len({id(uow) for uow in runs}) == 1
        assert domain.repository_for(Order).query.all().total == 0


def test_a_use_case_runs_once_on_a_version_conflict():
    domain, _, _, OrderServices, runs = _domain()

    with domain.domain_context():
        with pytest.raises(ExpectedVersionError):
            OrderServices().conflict()

    assert len(runs) == 1


def test_the_repository_page_says_a_get_returns_the_tracked_instance():
    text = _page("repository/references/unit-of-work.md")

    assert "returns the same object, with any changes made to it since" in text
    assert "two separate objects" not in text


def test_a_get_in_a_unit_of_work_returns_the_instance_already_tracked():
    domain, Order, *_ = _domain()

    with domain.domain_context():
        order = Order(name="placed")
        domain.repository_for(Order).add(order)

        with UnitOfWork() as uow:
            first = domain.repository_for(Order).get(order.id)
            first.name = "changed"
            second = domain.repository_for(Order).get(order.id)

            assert (Order, order.id) in uow._identity_map[Order.meta_.provider]
            assert second is first
            assert second.name == "changed"
