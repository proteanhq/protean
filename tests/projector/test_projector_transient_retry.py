"""Behavioral tests proving the shared handler wrapper honors per-projector
transient-retry options.

The wrapper (``protean.utils.mixins.handle``) already reads ``retries`` /
``backoff`` / ``retry_exceptions`` off ``meta_`` for any handler. Projectors
use that exact wrapper, so once the projector factory accepts the options, a
projector retries transient failures in place — mirroring event and command
handlers.
"""

from unittest.mock import patch

import pytest

from protean import current_domain
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.exceptions import TransactionError
from protean.fields import Identifier, String

from .elements import Registered, User


class UserReport(BaseProjection):
    user_id: Identifier(identifier=True)
    name: String()


@pytest.fixture(autouse=True)
def register(test_domain):
    test_domain.register(User)
    test_domain.register(Registered, part_of=User)
    test_domain.register(UserReport)


def _event():
    return Registered(user_id="1", email="john@example.com", name="John")


class TestProjectorTransientRetry:
    @patch("protean.utils.mixins.time.sleep")
    def test_projector_retries_on_transient_then_succeeds(
        self, mock_sleep, test_domain
    ):
        """The wrapper fires for a projector: a transient error is retried in
        place. Previously impossible — the factory rejected ``retries``."""
        attempts = 0

        class ReportProjector(BaseProjector):
            @on(Registered)
            def on_registered(self, event: Registered):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("transient")

        test_domain.register(
            ReportProjector,
            projector_for=UserReport,
            aggregates=[User],
            retries=2,
        )
        test_domain.init(traverse=False)

        ReportProjector._handle(_event())

        assert attempts == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_projector_retries_via_domain_toggle(self, mock_sleep, test_domain):
        """Parity path: a projector with no explicit ``retries`` still retries
        when the domain-wide ``server.transient_retry`` toggle is enabled."""
        test_domain.config["server"]["transient_retry"]["enabled"] = True
        attempts = 0

        class ReportProjector(BaseProjector):
            @on(Registered)
            def on_registered(self, event: Registered):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise ConnectionError("transient")

        test_domain.register(
            ReportProjector, projector_for=UserReport, aggregates=[User]
        )
        test_domain.init(traverse=False)

        ReportProjector._handle(_event())

        assert attempts == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_projector_retry_exceptions_cover_transaction_error(
        self, mock_sleep, test_domain
    ):
        """The issue's motivating case: a primary-key conflict surfaces as a
        ``TransactionError``, which the version/OCC retry does not cover.
        Listing it in ``retry_exceptions`` lets the losing run retry."""
        attempts = 0

        class ReportProjector(BaseProjector):
            @on(Registered)
            def on_registered(self, event: Registered):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise TransactionError("duplicate key")

        test_domain.register(
            ReportProjector,
            projector_for=UserReport,
            aggregates=[User],
            retries=4,
            retry_exceptions=["protean.exceptions.TransactionError"],
        )
        test_domain.init(traverse=False)

        ReportProjector._handle(_event())

        assert attempts == 2
        mock_sleep.assert_called_once()

    @patch("protean.utils.mixins.time.sleep")
    def test_transaction_error_not_retried_without_override(
        self, mock_sleep, test_domain
    ):
        """Negative path: ``TransactionError`` is outside the default transient
        set, so without adding it to ``retry_exceptions`` it propagates even
        when ``retries`` is set."""
        attempts = 0

        class ReportProjector(BaseProjector):
            @on(Registered)
            def on_registered(self, event: Registered):
                nonlocal attempts
                attempts += 1
                raise TransactionError("duplicate key")

        test_domain.register(
            ReportProjector,
            projector_for=UserReport,
            aggregates=[User],
            retries=4,
        )
        test_domain.init(traverse=False)

        with pytest.raises(TransactionError):
            ReportProjector._handle(_event())

        assert attempts == 1
        mock_sleep.assert_not_called()

    @patch("protean.utils.mixins.time.sleep")
    def test_failed_attempt_rolls_back_partial_write(self, mock_sleep, test_domain):
        """End-to-end against a real projection: because each attempt runs in a
        fresh Unit of Work, a read-model write from a failed attempt is rolled
        back before the retry. The first attempt writes a *leftover* record and
        then fails; if the UoW were not rolled back that record would survive
        alongside the real one, so asserting exactly one record (the real key)
        is what makes this non-vacuous."""
        attempts = 0

        class ReportProjector(BaseProjector):
            @on(Registered)
            def on_registered(self, event: Registered):
                nonlocal attempts
                attempts += 1
                repo = current_domain.repository_for(UserReport)
                if attempts == 1:
                    # Partial write that must NOT survive the failed attempt.
                    repo.add(UserReport(user_id="leftover", name="partial"))
                    raise TransactionError("failure after a partial write")
                repo.add(UserReport(user_id=event.user_id, name=event.name))

        test_domain.register(
            ReportProjector,
            projector_for=UserReport,
            aggregates=[User],
            retries=3,
            retry_exceptions=["protean.exceptions.TransactionError"],
        )
        test_domain.init(traverse=False)

        ReportProjector._handle(_event())

        assert attempts == 2
        mock_sleep.assert_called_once()

        reports = current_domain.repository_for(UserReport).query.all().items
        assert len(reports) == 1  # the "leftover" write was rolled back
        assert reports[0].user_id == "1"
        assert reports[0].name == "John"
