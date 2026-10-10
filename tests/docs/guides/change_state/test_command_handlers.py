"""Check what docs/guides/change-state/command-handlers.md says.

Each test loads its example fresh, so every test gets its own domain and its
own memory stores.
"""

import logging
import re
import subprocess
import sys

import pytest

from protean.core.unit_of_work import UnitOfWork
from tests.docs.support import DOCS_SRC, REPO_ROOT, load_example

pytestmark = pytest.mark.no_test_domain


@pytest.fixture
def publishing():
    module = load_example("guides/change-state/007.py")
    module.publishing.init(traverse=False)
    with module.publishing.domain_context():
        yield module


@pytest.fixture
def accounts():
    module = load_example("guides/change-state/command-handlers/001.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def payments():
    module = load_example("guides/change-state/command-handlers/002.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def error_handling():
    module = load_example("guides/change-state/command-handlers/003.py")
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


def no_backoff(module):
    """Keep the handler's retry count but sleep zero seconds between attempts."""
    module.domain.config["server"]["transient_retry"].update(
        base_delay_seconds=0.0, max_delay_seconds=0.0
    )


@pytest.fixture
def retrying():
    module = load_example("guides/change-state/command-handlers/004.py")
    no_backoff(module)
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def narrow_retrying():
    module = load_example("guides/change-state/command-handlers/005.py")
    no_backoff(module)
    module.domain.init(traverse=False)
    with module.domain.domain_context():
        yield module


@pytest.fixture
def failing_attempts(monkeypatch):
    """Make the first handler attempts fail with the given exceptions.

    The example handlers have empty bodies, so the failure is raised where each
    attempt opens its Unit of Work. Returns the list of attempts made.
    """
    attempts = []
    failures = []

    class UnitOfWorkThatFails(UnitOfWork):
        def __enter__(self):
            attempts.append(len(attempts) + 1)
            if failures:
                raise failures.pop(0)
            return super().__enter__()

    monkeypatch.setattr("protean.utils.mixins.UnitOfWork", UnitOfWorkThatFails)

    def fail_with(*exceptions):
        failures.extend(exceptions)
        return attempts

    return fail_with


def test_publish_article_command_publishes_the_draft(publishing):
    repo = publishing.publishing.repository_for(publishing.Article)
    repo.add(publishing.Article(article_id="1", status="DRAFT"))
    command = publishing.PublishArticle(article_id="1")

    publishing.publishing.process(command, asynchronous=False)

    refreshed = repo.get("1")
    assert refreshed.status == "PUBLISHED"
    assert refreshed.published_at == command.published_at


def test_publish_article_handler_raises_article_published(publishing):
    repo = publishing.publishing.repository_for(publishing.Article)
    repo.add(publishing.Article(article_id="2", status="DRAFT"))

    publishing.publishing.process(
        publishing.PublishArticle(article_id="2"), asynchronous=False
    )

    messages = publishing.publishing.event_store.store.read("publishing::article")
    events = [m for m in messages if m.metadata.domain.kind == "EVENT"]
    assert len(events) == 1
    assert events[0].metadata.headers.type == "Publishing.ArticlePublished.v1"
    assert events[0].data["article_id"] == "2"


def test_synchronous_processing_returns_the_new_account_id(accounts):
    command = accounts.RegisterCommand(email="jane@example.com", name="Jane Doe")

    account_id = accounts.register_account(command)

    account = accounts.domain.repository_for(accounts.Account).get(account_id)
    assert account.email == "jane@example.com"
    assert account.name == "Jane Doe"


def test_asynchronous_processing_returns_the_command_position(accounts):
    command = accounts.RegisterCommand(email="sam@example.com", name="Sam Lee")

    position = accounts.submit_registration(command)

    assert isinstance(position, int)
    stored = accounts.domain.event_store.store.read("accounts::account:command")
    assert len(stored) == 1
    assert stored[0].metadata.headers.type == "Accounts.RegisterCommand.v1"
    assert stored[0].data["email"] == "sam@example.com"
    # Without the engine running, the handler has not created the account.
    repo = accounts.domain.repository_for(accounts.Account)
    assert repo.query.filter(email="sam@example.com").all().total == 0


def test_handler_receives_the_idempotency_key(payments):
    payments.domain.process(
        payments.ChargeCard(account_id="acc-1", amount=25.0),
        asynchronous=False,
        idempotency_key="charge-acc-1-001",
    )

    assert payments.stripe.PaymentIntent.created == [
        {"amount": 25.0, "currency": "usd", "idempotency_key": "charge-acc-1-001"}
    ]


def test_handler_sees_no_key_when_none_is_given(payments):
    payments.domain.process(
        payments.ChargeCard(account_id="acc-1", amount=25.0), asynchronous=False
    )

    assert payments.stripe.PaymentIntent.created == [
        {"amount": 25.0, "currency": "usd", "idempotency_key": None}
    ]


def test_register_handler_runs_without_error(error_handling):
    result = error_handling.domain.process(
        error_handling.RegisterCommand(email="jane@example.com", name="Jane Doe"),
        asynchronous=False,
    )

    assert result is None


def test_handle_error_logs_the_failure(error_handling, caplog):
    with caplog.at_level(logging.ERROR, logger=error_handling.logger.name):
        error_handling.AccountCommandHandler.handle_error(
            ConnectionError("database is down"), message=None
        )

    assert [record.getMessage() for record in caplog.records] == [
        "Failed to process command: database is down"
    ]


def test_retry_options_are_set_on_the_handler(retrying):
    meta = retrying.AccountCommandHandler.meta_

    assert meta.retries == 3
    assert meta.backoff == "exponential"
    assert meta.retry_exceptions is None


def test_connection_error_is_retried_up_to_three_times(retrying, failing_attempts):
    attempts = failing_attempts(*[ConnectionError("database is down")] * 3)

    result = retrying.domain.process(
        retrying.DebitAccount(account_id="acc-1", amount=5.0), asynchronous=False
    )

    assert result is None
    assert attempts == [1, 2, 3, 4]


def test_connection_error_propagates_after_three_retries(retrying, failing_attempts):
    attempts = failing_attempts(*[ConnectionError("database is down")] * 4)

    with pytest.raises(ConnectionError, match="database is down"):
        retrying.domain.process(
            retrying.DebitAccount(account_id="acc-1", amount=5.0), asynchronous=False
        )

    assert attempts == [1, 2, 3, 4]


def test_narrowed_handler_retries_a_connection_error(narrow_retrying, failing_attempts):
    attempts = failing_attempts(*[ConnectionError("database is down")] * 2)

    narrow_retrying.domain.process(
        narrow_retrying.DebitAccount(account_id="acc-1", amount=5.0),
        asynchronous=False,
    )

    assert attempts == [1, 2, 3]


def test_narrowed_handler_does_not_retry_a_timeout_error(
    narrow_retrying, failing_attempts
):
    attempts = failing_attempts(TimeoutError("gateway timed out"))

    with pytest.raises(TimeoutError, match="gateway timed out"):
        narrow_retrying.domain.process(
            narrow_retrying.DebitAccount(account_id="acc-1", amount=5.0),
            asynchronous=False,
        )

    assert attempts == [1]


def test_page_test_passes_under_pytest():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(DOCS_SRC / "guides/change-state/007.py"),
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
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout), result.stdout
