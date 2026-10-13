"""The examples on ``docs/reference/server/supervisor.md`` behave as the page says."""

import logging
import shutil

import pytest

from protean import Domain
from protean.server.supervisor import Supervisor
from tests.docs.support import DOCS_SRC, load_example

pytestmark = pytest.mark.no_test_domain


def test_supervisor_holds_the_worker_count_and_log_level():
    supervisor = load_example("reference/server/supervisor/001.py").supervisor

    assert supervisor.domain_path == "my_package.domain"
    assert supervisor.num_workers == 4
    assert supervisor.test_mode is False
    assert supervisor.log_level == "INFO"
    # Nothing runs until run() is called.
    assert supervisor.workers == []
    assert supervisor.exit_code == 0


def test_configure_logging_sets_up_the_supervisor_root_logger():
    supervisor = load_example("reference/server/supervisor/002.py").supervisor

    root = logging.getLogger()
    assert root.level == logging.DEBUG
    # The handler the supervisor writes worker records with lets DEBUG through.
    assert any(
        type(handler) is logging.StreamHandler and handler.level == logging.DEBUG
        for handler in root.handlers
    )
    assert supervisor.num_workers == 4
    assert supervisor.log_level == "DEBUG"


@pytest.mark.parametrize(
    ("argument", "value", "message"),
    [
        ("log_level", "VERBOSE", "Invalid log_level 'VERBOSE'"),
        ("log_format", "xml", "Invalid log_format 'xml'"),
    ],
)
def test_a_log_value_the_cli_flags_reject_raises_value_error(argument, value, message):
    with pytest.raises(ValueError, match=message):
        Supervisor("my_package.domain", num_workers=4, **{argument: value})


def test_the_prerequisite_config_selects_stream_subscriptions(tmp_path):
    shutil.copy(
        DOCS_SRC / "reference/server/supervisor/stream_subscriptions.toml",
        tmp_path / "domain.toml",
    )
    domain = Domain(root_path=str(tmp_path), name="Workers")

    assert domain.config["server"]["default_subscription_type"] == "stream"
