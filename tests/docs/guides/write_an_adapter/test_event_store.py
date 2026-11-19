"""Run the example on ``docs/guides/write-an-adapter/event-store.md``.

The example is the ``delegating_event_store`` package. The event-store registry
stores the adapter by its dotted import path, so the package's folder goes on
``sys.path`` and the test imports it by name.
"""

import importlib
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator

import pytest

from tests.docs.support import (
    DOCS_SRC,
    REPO_ROOT,
    domain_from_config,
    outcome_counts,
)

_EXAMPLE = DOCS_SRC / "guides" / "write-an-adapter" / "event-store"
if str(_EXAMPLE) not in sys.path:
    sys.path.insert(0, str(_EXAMPLE))

import delegating_event_store

from protean.adapters.event_store.memory import MemoryEventStore
from protean.domain import Domain
from protean.port.event_store import EventStoreCapabilities

pytestmark = pytest.mark.no_test_domain

# The suite runs in a few seconds. The limit stops a run that hangs.
_CONFORMANCE_TIMEOUT = 300

# The single flags the suite gates tests on. A skip line never names a
# composite set such as BASIC.
_SINGLE_FLAGS = [
    EventStoreCapabilities.WRITE,
    EventStoreCapabilities.READ_STREAM,
    EventStoreCapabilities.READ_CATEGORY,
    EventStoreCapabilities.READ_ALL,
    EventStoreCapabilities.EXPECTED_VERSION,
    EventStoreCapabilities.CATEGORY_COMMIT_ORDER,
    EventStoreCapabilities.CONSUMER_GROUPS,
    EventStoreCapabilities.DURABLE,
    EventStoreCapabilities.SCHEMA_MANAGEMENT,
]


def _run_conformance_suite() -> subprocess.CompletedProcess[str]:
    """Run the event-store suite against the example, as a contributor would."""
    pythonpath = [str(_EXAMPLE)]
    if os.environ.get("PYTHONPATH"):
        pythonpath.append(os.environ["PYTHONPATH"])
    # The outer run's pytest and xdist settings must not reach the child run.
    env = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith("PYTEST_") and name != "PROTEAN_ENV"
    }
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/conformance/event_store",
            "-p",
            "delegating_event_store",
            "--port",
            "event_store",
            "--adapter",
            "delegating_memory",
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=_CONFORMANCE_TIMEOUT,
    )


@pytest.fixture(scope="module")
def conformance_run() -> subprocess.CompletedProcess[str]:
    return _run_conformance_suite()


@pytest.fixture
def domain(tmp_path) -> Iterator[Domain]:
    domain = domain_from_config(
        "guides/write-an-adapter/event-store/domain.toml", tmp_path
    )
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain


def test_conformance_suite_passes_against_the_example(conformance_run):
    output = conformance_run.stdout + conformance_run.stderr

    assert conformance_run.returncode == 0, output
    counts = outcome_counts(conformance_run)
    assert counts.get("passed", 0) > 0, output
    assert "failed" not in counts and "errors" not in counts, output


def test_conformance_run_executes_the_tests_the_declared_flags_gate(
    conformance_run, domain
):
    declared = domain.event_store._adapter.capabilities

    for flag in _SINGLE_FLAGS:
        skip_line = f"delegating_memory does not declare {flag.name}"
        if flag in declared:
            assert skip_line not in conformance_run.stdout, flag.name
        else:
            # The suite reports a flag the example does not declare as a skip.
            # Seeing that line shows the check above reads the real skip text.
            assert skip_line in conformance_run.stdout, flag.name


def test_example_declares_the_memory_store_flags(domain):
    adapter = domain.event_store._adapter

    assert adapter.capabilities == EventStoreCapabilities.CONSISTENT
    assert adapter.capabilities == adapter._delegate.capabilities


def test_domain_toml_builds_the_example_adapter(domain):
    adapter = domain.event_store._adapter

    assert isinstance(adapter, delegating_event_store.DelegatingEventStore)
    assert isinstance(adapter._delegate, MemoryEventStore)


def test_entry_point_names_the_register_function():
    path = _EXAMPLE / "entry-points.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    target = data["project"]["entry-points"]["protean.event_stores"][
        "delegating_memory"
    ]
    assert target == "delegating_event_store:register"

    module_name, attribute = target.split(":")
    resolved = getattr(importlib.import_module(module_name), attribute)
    assert resolved is delegating_event_store.register


def test_example_implements_every_port_member():
    cls = delegating_event_store.DelegatingEventStore

    assert cls.__abstractmethods__ == frozenset()
    # The suite resets the store with clear() and then close() after each test.
    assert "clear" in vars(cls)
    assert "close" in vars(cls)


def test_written_message_reaches_the_delegate(domain):
    adapter = domain.event_store._adapter
    adapter.write_message("order-1", "OrderPlaced", {"total": 10})

    rows = adapter._delegate.get_stream_messages("order-1")
    assert [(row["type"], row["data"]) for row in rows] == [
        ("OrderPlaced", {"total": 10})
    ]
