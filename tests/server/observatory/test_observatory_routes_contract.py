"""The routes ``create_api_router`` registers keep their public contract.

The Observatory serves ``/openapi.json``, and FastAPI builds each route's
``operationId`` from the handler's function name, its path and its method. The
operation's description comes from the handler's docstring, and its parameters
from the handler's signature. These tests pin all three, plus the order the
routes are registered in, because Starlette matches routes in that order
(``/traces/failed`` must come before ``/traces/{stream_id}``).
"""

from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from protean.server.observatory.api import create_api_router

# (path, method, operationId, first line of the description), in registration order.
_EXPECTED_ROUTES = [
    ("/health", "get", "health_health_get", "Infrastructure health check."),
    ("/outbox", "get", "outbox_outbox_get", "Outbox status for all domains."),
    (
        "/streams",
        "get",
        "streams_streams_get",
        "Stream lengths and consumer group info.",
    ),
    (
        "/consumers",
        "get",
        "consumers_consumers_get",
        "Per-consumer breakdown across all streams and consumer groups.",
    ),
    (
        "/workers",
        "get",
        "workers_workers_get",
        "Engine worker (pod) overview with per-worker throughput sparklines.",
    ),
    (
        "/queue-depth",
        "get",
        "queue_depth_queue_depth_get",
        "Queue depth snapshot for backpressure visualization.",
    ),
    (
        "/stats",
        "get",
        "stats_stats_get",
        "Aggregated throughput and error rate statistics.",
    ),
    (
        "/traces",
        "get",
        "traces_traces_get",
        "Recent trace history from the persisted Redis Stream.",
    ),
    (
        "/traces/stats",
        "get",
        "traces_stats_traces_stats_get",
        "Aggregated trace statistics for a time window.",
    ),
    (
        "/traces/timeline",
        "get",
        "traces_timeline_traces_timeline_get",
        "Pre-aggregated activity timeline buckets for the full time window.",
    ),
    (
        "/traces/overview",
        "get",
        "traces_overview_traces_overview_get",
        "Combined stats + timeline in a single XRANGE scan.",
    ),
    (
        "/traces/failed",
        "get",
        "traces_failed_traces_failed_get",
        "Failed and DLQ traces filtered by time window.",
    ),
    (
        "/traces/{stream_id}",
        "get",
        "trace_detail_traces__stream_id__get",
        "Fetch a single trace event by its Redis stream ID.",
    ),
    (
        "/subscriptions",
        "get",
        "subscriptions_subscriptions_get",
        "Subscription lag status for all domains.",
    ),
    (
        "/dlq",
        "get",
        "dlq_list_dlq_get",
        "List DLQ messages across all subscriptions.",
    ),
    (
        "/dlq/{dlq_id}",
        "get",
        "dlq_inspect_dlq__dlq_id__get",
        "Inspect a single DLQ message with full payload.",
    ),
    (
        "/dlq/{dlq_id}/replay",
        "post",
        "dlq_replay_dlq__dlq_id__replay_post",
        "Replay a single DLQ message back to its original stream.",
    ),
    (
        "/dlq/replay-all",
        "post",
        "dlq_replay_all_dlq_replay_all_post",
        "Replay all DLQ messages for a subscription.",
    ),
    (
        "/dlq",
        "delete",
        "dlq_purge_dlq_delete",
        "Purge all DLQ messages for a subscription.",
    ),
    (
        "/traces",
        "delete",
        "delete_traces_traces_delete",
        "Clear all persisted trace history.",
    ),
]

# operationId -> [(name, location, required, default)] in signature order.
_EXPECTED_PARAMETERS: dict[str, list[tuple[str, str, bool, Any]]] = {
    "traces_traces_get": [
        ("count", "query", False, 200),
        ("domain", "query", False, None),
        ("stream", "query", False, None),
        ("event", "query", False, None),
        ("message_id", "query", False, None),
    ],
    "traces_stats_traces_stats_get": [("window", "query", False, "5m")],
    "traces_timeline_traces_timeline_get": [("window", "query", False, "5m")],
    "traces_overview_traces_overview_get": [("window", "query", False, "5m")],
    "traces_failed_traces_failed_get": [
        ("window", "query", False, "5m"),
        ("handler", "query", False, None),
        ("message_type", "query", False, None),
        ("limit", "query", False, 25),
        ("offset", "query", False, 0),
        ("start", "query", False, None),
        ("end", "query", False, None),
    ],
    "trace_detail_traces__stream_id__get": [("stream_id", "path", True, None)],
    "dlq_list_dlq_get": [
        ("subscription", "query", False, None),
        ("limit", "query", False, 25),
        ("offset", "query", False, 0),
    ],
    "dlq_inspect_dlq__dlq_id__get": [("dlq_id", "path", True, None)],
    "dlq_replay_dlq__dlq_id__replay_post": [("dlq_id", "path", True, None)],
    "dlq_replay_all_dlq_replay_all_post": [("subscription", "query", True, None)],
    "dlq_purge_dlq_delete": [("subscription", "query", True, None)],
}


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(create_api_router([]))
    return app


def _operations(app: FastAPI) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (path, method): operation
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
    }


def _registered_order() -> list[tuple[str, str]]:
    router = create_api_router([])
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert routes, "Expected create_api_router to register routes"
    return [
        (route.path, method.lower())
        for route in routes
        for method in sorted(route.methods)
    ]


def test_routes_are_registered_in_the_expected_order():
    assert _registered_order() == [(p, m) for p, m, _, _ in _EXPECTED_ROUTES]


def test_every_route_keeps_its_operation_id_and_description():
    operations = _operations(_app())

    actual = {
        (path, method, op["operationId"], op["description"].splitlines()[0])
        for (path, method), op in operations.items()
    }

    assert actual == set(_EXPECTED_ROUTES)


def test_every_route_keeps_its_parameters():
    operations = _operations(_app())

    actual = {
        op["operationId"]: [
            (p["name"], p["in"], p["required"], p["schema"].get("default"))
            for p in op["parameters"]
        ]
        for op in operations.values()
        if op.get("parameters")
    }

    assert actual == _EXPECTED_PARAMETERS


def test_no_route_exposes_its_internal_arguments():
    names = {
        p["name"]
        for op in _operations(_app()).values()
        for p in op.get("parameters", [])
    }

    assert names, "Expected some routes to declare parameters"
    assert "domains" not in names
    assert "cache" not in names


def test_the_served_openapi_document_lists_every_operation_id():
    response = TestClient(_app()).get("/openapi.json")

    assert response.status_code == 200
    served = {
        op["operationId"]
        for operations in response.json()["paths"].values()
        for op in operations.values()
    }
    assert served == {op_id for _, _, op_id, _ in _EXPECTED_ROUTES}
