"""The examples on the FastAPI integration guide behave as the page says."""

import asyncio
import re
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.docs.support import DOCS_SRC, load_example
from tests.support.lifespan import empty_with_blocks, lifespan_yields

pytestmark = [pytest.mark.no_test_domain, pytest.mark.fastapi]


def test_requests_run_inside_the_domain_their_path_prefix_maps_to():
    example = load_example("guides/fastapi/index/001.py")
    client = TestClient(example.app)

    assert client.get("/customers/42").json() == {"domain": "Identity"}
    assert client.get("/products/7").json() == {"domain": "Catalogue"}
    # A path that matches no prefix runs without a domain context.
    assert client.get("/health").json() == {"domain": None}


def test_the_longest_matching_prefix_wins():
    example = load_example("guides/fastapi/index/002.py")
    client = TestClient(example.app)

    assert client.get("/api/v2/items").json() == {"domain": "V2"}
    assert client.get("/api/v1/items").json() == {"domain": "Core"}


def test_a_resolver_picks_the_domain_and_none_means_no_context():
    example = load_example("guides/fastapi/index/003.py")
    client = TestClient(example.app)

    assert client.get("/tenant-a/orders").json() == {"domain": "TenantA"}
    assert client.get("/tenant-b/orders").json() == {"domain": "TenantB"}
    assert client.get("/status").json() == {"domain": None}


def test_the_root_prefix_maps_every_path_to_the_single_domain():
    example = load_example("guides/fastapi/index/004.py")
    client = TestClient(example.app)

    assert client.get("/").json() == {"domain": "Shop"}
    assert client.get("/orders/1/items").json() == {"domain": "Shop"}


@pytest.mark.parametrize(
    ("kind", "status", "error"),
    [
        ("validation", 400, {"name": ["is required"]}),
        ("invalid-data", 400, {"name": ["is too long"]}),
        ("value", 400, "quantity must be positive"),
        ("not-found", 404, "Customer 42 does not exist"),
        ("invalid-state", 409, "Order is already shipped"),
        ("invalid-operation", 422, "Cannot cancel a paid order"),
    ],
)
def test_each_domain_exception_maps_to_the_status_in_the_table(kind, status, error):
    example = load_example("guides/fastapi/index/005.py")
    example.domain.init(traverse=False)
    client = TestClient(example.app)

    response = client.get(f"/raise/{kind}")

    assert response.status_code == status
    assert response.json() == {
        "error": error,
        "correlation_id": response.headers["X-Correlation-ID"],
    }


def test_a_missing_customer_becomes_a_404_and_a_stored_one_a_200():
    example = load_example("guides/fastapi/index/005.py")
    example.domain.init(traverse=False)
    client = TestClient(example.app)

    with example.domain.domain_context():
        customer = example.Customer(name="Alice")
        example.domain.repository_for(example.Customer).add(customer)

    found = client.get(f"/customers/{customer.id}")
    missing = client.get("/customers/does-not-exist")

    assert found.status_code == 200
    assert found.json() == {"id": customer.id, "name": "Alice"}
    assert missing.status_code == 404
    assert missing.json() == {
        "error": "`Customer` object with identifier does-not-exist does not exist.",
        "correlation_id": missing.headers["X-Correlation-ID"],
    }


def _commands(example):
    with example.domain.domain_context():
        return example.domain.event_store.store.read("ordering::order:command")


def test_place_order_accepts_and_the_command_carries_the_header_correlation_id():
    example = load_example("guides/fastapi/index/006.py")
    example.domain.init(traverse=False)
    client = TestClient(example.app)

    response = client.post(
        "/orders",
        json={"customer_id": "cust-1"},
        headers={"X-Correlation-ID": "req-abc-123"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert response.headers["X-Correlation-ID"] == "req-abc-123"
    commands = _commands(example)
    assert len(commands) == 1
    assert commands[0].metadata.domain.correlation_id == "req-abc-123"


def test_an_invalid_command_comes_back_as_a_400_through_the_exception_handlers():
    example = load_example("guides/fastapi/index/006.py")
    example.domain.init(traverse=False)
    client = TestClient(example.app, raise_server_exceptions=False)

    response = client.post("/orders", json={})

    assert response.status_code == 400
    assert response.json() == {
        "error": {"customer_id": ["is required"]},
        "correlation_id": response.headers["X-Correlation-ID"],
    }
    assert _commands(example) == []


def test_x_request_id_is_the_fallback_and_no_header_gets_a_generated_id():
    example = load_example("guides/fastapi/index/006.py")
    example.domain.init(traverse=False)
    client = TestClient(example.app)

    fallback = client.post(
        "/orders", json={"customer_id": "c1"}, headers={"X-Request-ID": "req-9"}
    )
    generated = client.post("/orders", json={"customer_id": "c2"})

    assert fallback.headers["X-Correlation-ID"] == "req-9"
    assert re.fullmatch(r"[0-9a-f]{32}", generated.headers["X-Correlation-ID"])
    ids = [c.metadata.domain.correlation_id for c in _commands(example)]
    assert ids == ["req-9", generated.headers["X-Correlation-ID"]]


def test_the_lifespan_initializes_the_domain_and_sets_up_the_database():
    example = load_example("guides/fastapi/index/007.py")
    assert example.domain.event_store.store is None

    with TestClient(example.app) as client:
        assert example.domain.event_store.store is not None
        order_id = client.post("/orders", json={"customer_name": "Alice"}).json()["id"]
        response = client.get(f"/orders/{order_id}")

    assert response.status_code == 200
    assert response.json() == {"id": order_id, "customer_name": "Alice"}


def test_the_multi_domain_lifespan_initializes_every_domain():
    example = load_example("guides/fastapi/index/008.py")
    domains = [example.identity_domain, example.catalogue_domain]
    assert all(d.event_store.store is None for d in domains)

    with TestClient(example.app) as client:
        assert all(d.event_store.store is not None for d in domains)
        assert client.get("/customers/1").json() == {"domain": "Identity"}
        assert client.get("/products/1").json() == {"domain": "Catalogue"}


def test_the_lifespan_closes_the_domain_on_shutdown_and_not_before():
    example = load_example("guides/fastapi/index/007.py")

    with patch.object(example.domain, "close", wraps=example.domain.close) as close:
        with TestClient(example.app) as client:
            client.post("/orders", json={"customer_name": "Alice"})
            assert close.call_count == 0

    close.assert_called_once_with()


def test_the_lifespan_closes_the_domain_when_the_app_exits_on_an_error():
    example = load_example("guides/fastapi/index/007.py")

    with patch.object(example.domain, "close", wraps=example.domain.close) as close:
        with pytest.raises(RuntimeError, match="app stopped"):
            with TestClient(example.app):
                raise RuntimeError("app stopped")

    close.assert_called_once_with()


def test_the_lifespan_closes_the_domain_when_an_error_reaches_the_yield():
    example = load_example("guides/fastapi/index/007.py")

    async def throw_at_the_yield():
        cm = example.lifespan(example.app)
        await cm.__aenter__()
        error = RuntimeError("cancelled")
        # False means the error was not swallowed and goes on to the caller.
        return await cm.__aexit__(RuntimeError, error, None)

    with patch.object(example.domain, "close", wraps=example.domain.close) as close:
        assert asyncio.run(throw_at_the_yield()) is False

    close.assert_called_once_with()


def test_the_lifespan_closes_the_domain_when_database_setup_fails():
    example = load_example("guides/fastapi/index/007.py")
    failing_setup = patch.object(
        example.domain, "setup_database", side_effect=RuntimeError("setup failed")
    )

    with patch.object(example.domain, "close", wraps=example.domain.close) as close:
        with failing_setup, pytest.raises(RuntimeError, match="setup failed"):
            with TestClient(example.app):
                pass

    close.assert_called_once_with()


def _record_closes(domains, closed):
    """Patch ``close`` on each domain to record its name, then really close it."""
    patches = []
    for d in domains:

        def recording_close(d=d, original=d.close):
            closed.append(d.name)
            original()

        patches.append(patch.object(d, "close", side_effect=recording_close))
    return patches


def test_the_multi_domain_lifespan_closes_every_domain_in_reverse_order():
    example = load_example("guides/fastapi/index/008.py")
    closed = []
    patches = _record_closes(
        [example.identity_domain, example.catalogue_domain], closed
    )

    with patches[0], patches[1]:
        with TestClient(example.app):
            assert closed == []

    assert closed == ["Catalogue", "Identity"]


def test_the_multi_domain_lifespan_closes_only_the_domains_that_started():
    example = load_example("guides/fastapi/index/008.py")
    closed = []
    patches = _record_closes(
        [example.identity_domain, example.catalogue_domain], closed
    )
    failing_init = patch.object(
        example.catalogue_domain, "init", side_effect=RuntimeError("init failed")
    )

    with patches[0], patches[1], failing_init:
        with pytest.raises(RuntimeError, match="init failed"):
            with TestClient(example.app):
                pass

    assert closed == ["Identity"]


@pytest.mark.parametrize("path", ["007.py", "008.py"])
def test_every_lifespan_yield_sits_in_a_try_that_closes_the_domain(path):
    source = (DOCS_SRC / "guides/fastapi/index" / path).read_text(encoding="utf-8")

    yields = lifespan_yields(source)

    assert yields
    assert all(closed for _, closed in yields), yields
    assert empty_with_blocks(source) == []


def test_the_empty_block_check_flags_a_with_whose_body_is_pass():
    empty = (
        "async def lifespan(app):\n"
        "    yield\n"
        "    with domain.domain_context():\n"
        "        pass\n"
    )
    full = (
        "async def lifespan(app):\n"
        "    with domain.domain_context():\n"
        "        domain.setup_database()\n"
        "    yield\n"
    )

    assert empty_with_blocks(empty) == [3]
    assert empty_with_blocks(full) == []


def test_the_yield_check_flags_a_bare_yield_and_a_finally_without_close():
    bare = "async def lifespan(app):\n    domain.init()\n    yield\n"
    no_close = (
        "async def lifespan(app):\n"
        "    try:\n"
        "        yield\n"
        "    finally:\n"
        "        domain.flush()\n"
    )
    closed = (
        "async def lifespan(app):\n"
        "    try:\n"
        "        yield\n"
        "    finally:\n"
        "        domain.close()\n"
    )

    assert lifespan_yields(bare) == [(3, False)]
    assert lifespan_yields(no_close) == [(3, False)]
    assert lifespan_yields(closed) == [(3, True)]
    assert lifespan_yields("async def other(app):\n    yield\n") == []


def test_module_level_init_lets_requests_use_the_domain_at_once():
    example = load_example("guides/fastapi/index/009.py")

    assert example.domain.event_store.store is not None
    response = TestClient(example.app).post("/orders", json={"customer_name": "Bob"})
    assert response.status_code == 200
    with example.domain.domain_context():
        order = example.domain.repository_for(example.Order).get(response.json()["id"])
    assert order.customer_name == "Bob"
