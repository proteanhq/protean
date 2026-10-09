"""The engine on the run-the-server guide behaves as the page says."""

import signal
import subprocess
import sys
import textwrap
import threading
from pathlib import Path

import pytest

from protean.server import Engine
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

EXAMPLE_PATH = Path(__file__).parents[4] / "docs_src/guides/server/index/001.py"

# Loads the example, stores one event, then calls the named serve function.
_SERVE = textwrap.dedent(
    """
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("example", sys.argv[1])
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        example.place_order("ord-1")
        getattr(example, sys.argv[2])()
    """
)


def _serve_until_handled_then_signal(function_name, sig):
    process = subprocess.Popen(
        [sys.executable, "-c", _SERVE, str(EXAMPLE_PATH), function_name],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Killing the child closes its stdout, which ends the read loop below if
    # the engine never prints the line it is waiting for.
    deadline = threading.Timer(60, process.kill)
    deadline.start()
    try:
        lines = []
        for line in process.stdout:
            lines.append(line)
            if line.strip() == "Handled ord-1":
                break
        deadline.cancel()
        assert "Handled ord-1\n" in lines, "".join(lines)
        assert process.poll() is None, "the engine stopped without a signal"
        process.send_signal(sig)
        process.communicate(timeout=30)
    finally:
        deadline.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()
    return process.returncode


def test_test_mode_handles_the_waiting_event_and_returns():
    example = load_example("guides/server/index/001.py")
    example.domain.init(traverse=False)

    with example.domain.domain_context():
        example.place_order("ord-1")
        engine = Engine(example.domain, test_mode=True)
        engine.run()

    assert example.placed_orders == ["ord-1"]
    assert engine.exit_code == 0


@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM, signal.SIGHUP])
def test_serve_handles_events_until_a_signal_and_exits_with_zero(sig):
    assert _serve_until_handled_then_signal("serve", sig) == 0


def test_the_debug_engine_also_serves_until_a_signal():
    returncode = _serve_until_handled_then_signal(
        "serve_with_debug_logging", signal.SIGTERM
    )

    assert returncode == 0
