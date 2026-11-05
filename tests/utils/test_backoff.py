"""``AdaptiveBackoff``: a wait that doubles on idle polls, up to a cap."""

import inspect
import logging

import pytest

import protean.utils
from protean.utils import backoff as backoff_module
from protean.utils.backoff import AdaptiveBackoff


def test_wait_starts_at_base():
    backoff = AdaptiveBackoff(0.5, 4)

    assert backoff.current == 0.5
    assert backoff.base == 0.5
    assert backoff.cap == 4.0


def test_idle_polls_double_the_wait_up_to_the_cap():
    backoff = AdaptiveBackoff(0.5, 4)

    assert [backoff.on_idle() for _ in range(5)] == [1.0, 2.0, 4.0, 4.0, 4.0]
    assert backoff.current == 4.0


def test_activity_resets_the_wait_to_base():
    backoff = AdaptiveBackoff(0.5, 4)
    backoff.on_idle()
    backoff.on_idle()

    assert backoff.on_activity() == 0.5
    assert backoff.current == 0.5


def test_reset_sets_the_wait_back_to_base():
    backoff = AdaptiveBackoff(0.5, 4)
    backoff.on_idle()

    assert backoff.reset() == 0.5
    assert backoff.current == 0.5


def test_start_gives_a_zero_base_a_value_to_double_from():
    backoff = AdaptiveBackoff(0, 1, start=0.01)

    waits = [backoff.on_idle() for _ in range(9)]

    assert waits == pytest.approx([0.01, 0.02, 0.04, 0.08, 0.16, 0.32, 0.64, 1.0, 1.0])
    assert backoff.on_activity() == 0


def test_zero_base_without_start_stays_zero():
    backoff = AdaptiveBackoff(0, 5)

    assert [backoff.on_idle() for _ in range(3)] == [0, 0, 0]


def test_start_does_not_pass_a_zero_cap():
    backoff = AdaptiveBackoff(0, 0, start=0.01)

    assert [backoff.on_idle() for _ in range(3)] == [0, 0, 0]


def test_cap_below_base_is_raised_to_base():
    backoff = AdaptiveBackoff(2, 0.5)

    assert backoff.cap == 2.0
    assert [backoff.on_idle() for _ in range(3)] == [2.0, 2.0, 2.0]


def test_cap_equal_to_base_never_grows():
    backoff = AdaptiveBackoff(1, 1)

    assert [backoff.on_idle() for _ in range(3)] == [1.0, 1.0, 1.0]


def test_backoff_logs_nothing(caplog):
    caplog.set_level(logging.DEBUG)
    backoff = AdaptiveBackoff(0, 0.5, start=0.01)
    for _ in range(8):
        backoff.on_idle()
    backoff.on_activity()
    AdaptiveBackoff(2, 1)

    assert caplog.records == []


def test_protean_utils_does_not_re_export_the_helper():
    assert not hasattr(protean.utils, "AdaptiveBackoff")


def test_helper_source_names_no_event_store():
    assert "event_store" not in inspect.getsource(backoff_module)
