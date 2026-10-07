"""Run the examples on ``docs/reference/adapters/broker/inline.md``."""

import subprocess
import sys

import pytest

from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain


def test_subscriber_is_called_on_publish():
    example = load_example("adapters/broker/inline/001.py")

    assert example.created == ["123"]


def test_each_consumer_group_receives_every_message():
    example = load_example("adapters/broker/inline/001.py")

    expected = {"type": "order.created", "order_id": "A1"}
    assert example.billing_message == expected
    assert example.shipping_message == expected


def test_a_group_gets_each_message_once():
    example = load_example("adapters/broker/inline/001.py")

    with example.domain.domain_context():
        broker = example.domain.brokers["default"]
        broker.publish("invoices", {"invoice_id": "I1"})

        identifier, message = broker.get_next("invoices", "billing")
        assert message == {"invoice_id": "I1"}
        # Not acknowledged yet, and still not handed out a second time
        assert broker.get_next("invoices", "billing") is None
        assert broker.ack("invoices", identifier, "billing") is True


def test_domain_fixture_example_defines_a_subscriber():
    example = load_example("adapters/broker/inline/002.py")

    assert example.processed == []
    assert example.testing_domain.config["message_processing"] == "sync"


def test_domain_fixture_example_passes_under_pytest():
    # Run the file the way a reader would: as a pytest module, with its own
    # fixtures. A collection warning (for example a class named Test*) fails it.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "adapters/broker/inline/002.py"),
            "-p",
            "no:cacheprovider",
            "-p",
            "no:randomly",
            "-q",
            "--import-mode=importlib",
            "-W",
            "error::pytest.PytestCollectionWarning",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 passed" in result.stdout
