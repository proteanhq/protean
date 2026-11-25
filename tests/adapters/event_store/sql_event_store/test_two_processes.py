"""Two processes append through domains that share one SQLite file.

Every transaction on the shared file starts with ``BEGIN IMMEDIATE``, so the
second writer waits for the busy timeout instead of failing with
``database is locked``.
"""

import multiprocessing
import traceback
from pathlib import Path
from typing import Any

import pytest

from protean import Domain
from protean.core.unit_of_work import UnitOfWork

from .conftest import shared_database

APPENDS_PER_PROCESS = 200


def build_domain(tmp_path: Path) -> Domain:
    domain = Domain(name="TwoProcesses")
    domain.config["databases"]["default"] = shared_database("sqlite", tmp_path)
    domain.config["event_store"] = {"provider": "sql"}
    domain.init(traverse=False)
    return domain


def append_events(tmp_path: Path, writer: str, errors: Any, start: Any) -> None:
    """Append ``APPENDS_PER_PROCESS`` events, one Unit of Work each, once
    both processes reach ``start``.

    Runs in a child process, so it reports a failure through ``errors``.
    """
    try:
        domain = build_domain(tmp_path)
        with domain.domain_context():
            store = domain.event_store._require_adapter()
            # The domain is built in each process first, so both start to
            # write together.
            start.wait(timeout=60)
            for index in range(APPENDS_PER_PROCESS):
                with UnitOfWork():
                    store.write_message(f"{writer}-{index}", "Written", {})
            store.close()
    except BaseException:  # sent to the parent, which fails the test
        errors.put(traceback.format_exc())


@pytest.mark.sqlite
@pytest.mark.no_test_domain
def test_two_processes_append_every_event(tmp_path):
    domain = build_domain(tmp_path)
    with domain.domain_context():
        store = domain.event_store._require_adapter()
        store.create_schema()

        context = multiprocessing.get_context("spawn")
        errors = context.Queue()
        start = context.Barrier(2)
        processes = [
            context.Process(
                target=append_events, args=(tmp_path, writer, errors, start)
            )
            for writer in ("left", "right")
        ]
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=120)
        alive = [process for process in processes if process.is_alive()]
        for process in alive:
            process.kill()

        assert alive == []
        reported = []
        while not errors.empty():
            reported.append(errors.get())
        assert reported == []

        positions = [
            row["global_position"]
            for row in store.get_all_messages(limit=2 * APPENDS_PER_PROCESS + 1)
        ]
        assert positions == list(range(1, 2 * APPENDS_PER_PROCESS + 1))
        store.close()
