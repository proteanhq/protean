"""The add-domain-service-flow assets: one aggregate per handler, and repeats.

Each asset's command handler runs a domain service over two aggregates and
persists only the primary one. The other aggregate changes later, through an
event and a command. Running the command with asynchronous event processing,
and no server, stops the flow after the first handler. The other aggregate
must then be exactly as it was saved, and the handler must not have called
``repository.add`` on it.

The other tests drive the full flow and check that a repeated command, a
reused id, or a late event changes nothing.
"""

from __future__ import annotations

import itertools
import runpy
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from protean import dx
from protean.domain import Domain
from protean.exceptions import ValidationError
from protean.utils.sync_dispatch import dispatch_events_sync

pytestmark = pytest.mark.no_test_domain

PACK_ROOT = Path(str(dx.pack_files()))
ASSETS = PACK_ROOT / dx.SKILLS_DIR / "add-domain-service-flow" / "assets"

if not PACK_ROOT.is_dir():
    pytest.skip(
        "DX pack is not unpacked on disk; the assets are executed by path",
        allow_module_level=True,
    )

Namespace = dict[str, Any]
_run_names = itertools.count()


def _load(asset: str, event_processing: str = "sync") -> tuple[Namespace, Domain]:
    ns = runpy.run_path(
        str(ASSETS / asset), run_name=f"_one_aggregate_{next(_run_names)}_"
    )
    domain = ns["domain"]
    domain.config["event_processing"] = event_processing
    domain.config["command_processing"] = "sync"
    domain.init(traverse=False)
    return ns, domain


def _event_names(domain: Domain) -> list[str]:
    messages = domain.event_store.store.read("$all")
    return [type(message.to_domain_object()).__name__ for message in messages]


def _record_spans(domain: Domain) -> Any:
    """Send the domain's spans to an in-memory exporter and return it."""
    sdk_trace = pytest.importorskip("opentelemetry.sdk.trace")
    export = pytest.importorskip("opentelemetry.sdk.trace.export")
    in_memory = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter"
    )
    exporter = in_memory.InMemorySpanExporter()
    provider = sdk_trace.TracerProvider()
    provider.add_span_processor(export.SimpleSpanProcessor(exporter))
    domain._otel_tracer_provider = provider
    domain._otel_init_attempted = True
    return exporter


def _saves_by_type(exporter: Any) -> Counter[str]:
    """Count ``repository.add`` calls per aggregate type, event store writes aside.

    A save of an unchanged aggregate writes nothing to the store, so only the
    call count shows a handler that saves a second aggregate.
    """
    return Counter(
        span.attributes["protean.aggregate.type"]
        for span in exporter.get_finished_spans()
        if span.name == "protean.repository.add"
        and span.attributes["protean.aggregate.type"] != "MemoryMessage"
    )


def _transfer(ns: Namespace, domain: Domain) -> None:
    repo = domain.repository_for(ns["Account"])
    repo.add(ns["Account"](account_id="A-1", owner="Ann", balance=100.0))
    domain.process(
        ns["TransferFunds"](
            transfer_id="T-1", source_id="A-1", target_id="B-1", amount=40.0
        )
    )
    assert repo.get("A-1").balance == 60.0


def _enroll(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Course"]).add(
        ns["Course"](course_id="C-1", title="Algebra", capacity=30)
    )
    domain.process(ns["EnrollStudent"](course_id="C-1", student_id="S-1"))
    assert domain.repository_for(ns["Course"]).get("C-1").student_ids == ["S-1"]


def _reserve(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Room"]).add(
        ns["Room"](room_id="R-1", name="Oak", capacity=8)
    )
    domain.process(
        ns["ReserveRoom"](reservation_id="RES-1", room_id="R-1", requester_id="P-1")
    )
    assert domain.repository_for(ns["Room"]).get("R-1").reserved_by == "P-1"


# For each asset: the step that runs the primary command, the event it hands
# off with, the other aggregate as (class name, field values), and the
# repository.add calls the whole step makes per aggregate type. Each step saves
# its own setup aggregate once, so a count of 2 means the handler saved the
# primary aggregate once and nothing else.
PRIMARY_STEPS: dict[
    str,
    tuple[Callable[[Namespace, Domain], None], str, str, dict[str, Any], Counter[str]],
] = {
    "domain_service_flow_basic.py": (
        _transfer,
        "FundsDebited",
        "Account",
        {"account_id": "B-1", "owner": "Bob"},
        Counter({"Account": 2}),
    ),
    "domain_service_flow_in_handler.py": (
        _enroll,
        "StudentEnrolled",
        "Student",
        {"student_id": "S-1", "name": "Ann"},
        Counter({"Course": 2}),
    ),
    "domain_service_flow_invariants.py": (
        _reserve,
        "RoomReserved",
        "Requester",
        {"requester_id": "P-1", "name": "Ann", "authorization_level": 2},
        Counter({"Room": 2}),
    ),
}


@pytest.mark.parametrize("asset", sorted(PRIMARY_STEPS))
def test_the_command_handler_persists_only_the_primary_aggregate(asset: str) -> None:
    ns, domain = _load(asset, event_processing="async")
    step, event_name, other_name, other_values, saves = PRIMARY_STEPS[asset]

    with domain.domain_context():
        other_repo = domain.repository_for(ns[other_name])
        other = ns[other_name](**other_values)
        other_repo.add(other)
        other_id = next(iter(other_values.values()))
        before = other_repo.get(other_id).to_dict()
        exporter = _record_spans(domain)

        step(ns, domain)

        # The event that hands off to the other aggregate was raised, but no
        # server ran to deliver it.
        assert event_name in _event_names(domain)
        assert other_repo.get(other_id).to_dict() == before
        assert _saves_by_type(exporter) == saves


# --- Funds transfer: the debit and the credit apply once per transfer id ---


def _balances(ns: Namespace, domain: Domain) -> tuple[float, float]:
    repo = domain.repository_for(ns["Account"])
    return repo.get("A-1").balance, repo.get("B-1").balance


def _open_accounts(ns: Namespace, domain: Domain) -> None:
    repo = domain.repository_for(ns["Account"])
    repo.add(ns["Account"](account_id="A-1", owner="Ann", balance=100.0))
    repo.add(ns["Account"](account_id="B-1", owner="Bob", balance=0.0))


@pytest.mark.parametrize("repeat_amount", [40.0, 10.0])
def test_a_repeated_transfer_id_moves_no_money(repeat_amount: float) -> None:
    ns, domain = _load("domain_service_flow_basic.py")
    with domain.domain_context():
        _open_accounts(ns, domain)
        for amount in (40.0, repeat_amount):
            domain.process(
                ns["TransferFunds"](
                    transfer_id="T-1", source_id="A-1", target_id="B-1", amount=amount
                )
            )

        assert _balances(ns, domain) == (60.0, 40.0)
        assert domain.repository_for(ns["Account"]).get("A-1").applied_transfer_ids == [
            "T-1"
        ]


def test_a_transfer_id_reused_in_the_other_direction_moves_no_money() -> None:
    ns, domain = _load("domain_service_flow_basic.py")
    with domain.domain_context():
        _open_accounts(ns, domain)
        domain.process(
            ns["TransferFunds"](
                transfer_id="T-1", source_id="A-1", target_id="B-1", amount=40.0
            )
        )
        domain.process(
            ns["TransferFunds"](
                transfer_id="T-1", source_id="B-1", target_id="A-1", amount=40.0
            )
        )

        assert _balances(ns, domain) == (60.0, 40.0)


# --- Course enrollment: no second seat, and a late event changes nothing ---


def test_a_repeated_enrollment_takes_no_second_seat() -> None:
    ns, domain = _load("domain_service_flow_in_handler.py")
    with domain.domain_context():
        domain.repository_for(ns["Course"]).add(
            ns["Course"](course_id="C-1", title="Algebra", capacity=30)
        )
        domain.repository_for(ns["Student"]).add(
            ns["Student"](student_id="S-1", name="Ann")
        )
        for _ in range(2):
            domain.process(ns["EnrollStudent"](course_id="C-1", student_id="S-1"))

        assert domain.repository_for(ns["Course"]).get("C-1").student_ids == ["S-1"]
        assert _event_names(domain).count("StudentEnrolled") == 1


def test_a_late_enrollment_event_does_not_undo_a_later_one() -> None:
    ns, domain = _load("domain_service_flow_in_handler.py")
    with domain.domain_context():
        for course_id in ("C-1", "C-2"):
            domain.repository_for(ns["Course"]).add(
                ns["Course"](course_id=course_id, title=course_id, capacity=30)
            )
        domain.repository_for(ns["Student"]).add(
            ns["Student"](student_id="S-1", name="Ann")
        )
        domain.process(ns["EnrollStudent"](course_id="C-1", student_id="S-1"))
        domain.process(ns["EnrollStudent"](course_id="C-2", student_id="S-1"))

        messages = domain.event_store.store.read("$all")
        events = [message.to_domain_object() for message in messages]
        first = next(e for e in events if type(e).__name__ == "StudentEnrolled")
        assert first.course_id == "C-1"
        dispatch_events_sync([first], domain.handlers_for)

        student = domain.repository_for(ns["Student"]).get("S-1")
        assert student.course_ids == ["C-1", "C-2"]


# --- Room reservations: releasing frees a place under the limit ---


def _reserve_rooms(ns: Namespace, domain: Domain, indexes: range) -> None:
    for index in indexes:
        domain.repository_for(ns["Room"]).add(
            ns["Room"](room_id=f"R-{index}", name=f"Room {index}", capacity=8)
        )
        domain.process(
            ns["ReserveRoom"](
                reservation_id=f"RES-{index}",
                room_id=f"R-{index}",
                requester_id="P-1",
            )
        )


def _requester(ns: Namespace, domain: Domain) -> None:
    domain.repository_for(ns["Requester"]).add(
        ns["Requester"](requester_id="P-1", name="Ann", authorization_level=2)
    )


def test_the_reservation_limit_blocks_a_fourth_active_reservation() -> None:
    ns, domain = _load("domain_service_flow_invariants.py")
    with domain.domain_context():
        _requester(ns, domain)
        _reserve_rooms(ns, domain, range(1, 4))

        with pytest.raises(ValidationError) as exc:
            _reserve_rooms(ns, domain, range(4, 5))
        assert exc.value.messages == {"_service": ["Maximum reservation limit reached"]}


def test_releasing_a_room_frees_a_reservation_under_the_limit() -> None:
    ns, domain = _load("domain_service_flow_invariants.py")
    with domain.domain_context():
        _requester(ns, domain)
        _reserve_rooms(ns, domain, range(1, 4))
        for _ in range(2):
            domain.process(ns["ReleaseRoom"](room_id="R-1", reservation_id="RES-1"))

        requester = domain.repository_for(ns["Requester"]).get("P-1")
        assert requester.released_reservation_ids == ["RES-1"]
        assert requester.active_reservation_count() == 2
        assert _event_names(domain).count("RoomReleased") == 1

        _reserve_rooms(ns, domain, range(4, 5))
        room = domain.repository_for(ns["Room"]).get("R-4")
        assert room.reserved_by == "P-1"


def test_a_release_recorded_before_its_reservation_still_counts() -> None:
    ns, domain = _load("domain_service_flow_invariants.py")
    with domain.domain_context():
        requester = ns["Requester"](requester_id="P-1", name="Ann")
        requester.record_release("RES-1")
        requester.record_reservation("RES-1")

        assert requester.active_reservation_count() == 0


@pytest.mark.parametrize("released", [False, True])
def test_a_reused_reservation_id_cannot_hold_a_second_room(released: bool) -> None:
    ns, domain = _load("domain_service_flow_invariants.py")
    with domain.domain_context():
        _requester(ns, domain)
        _reserve_rooms(ns, domain, range(1, 2))
        if released:
            domain.process(ns["ReleaseRoom"](room_id="R-1", reservation_id="RES-1"))
        domain.repository_for(ns["Room"]).add(
            ns["Room"](room_id="R-2", name="Room 2", capacity=8)
        )

        with pytest.raises(ValidationError) as exc:
            domain.process(
                ns["ReserveRoom"](
                    reservation_id="RES-1", room_id="R-2", requester_id="P-1"
                )
            )

        assert exc.value.messages == {"_service": ["Reservation id is already in use"]}
        assert domain.repository_for(ns["Room"]).get("R-2").status == "available"
