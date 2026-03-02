"""Tests for CommandProcessor — the extracted command processing logic.

These tests exercise the CommandProcessor through the Domain's delegation
methods (``domain.process()``, ``domain.command_handler_for()``, and
``domain._enrich_command()``) to verify that the extraction preserves
correct behavior.
"""

from uuid import uuid4

import pytest

from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.exceptions import ConfigurationError
from protean.fields import Identifier, String
from protean.utils.mixins import handle


# ─── Shared domain elements ─────────────────────────────────────────────


class Account(BaseAggregate):
    account_id: Identifier(identifier=True)
    name: String(required=True)


class OpenAccount(BaseCommand):
    account_id: Identifier(identifier=True)
    name: String(required=True)


class CloseAccount(BaseCommand):
    account_id: Identifier(identifier=True)


class AccountCommandHandler(BaseCommandHandler):
    @handle(OpenAccount)
    def open(self, command: OpenAccount):
        return {"opened": command.account_id}


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Account)
    test_domain.register(OpenAccount, part_of=Account)
    test_domain.register(CloseAccount, part_of=Account)
    test_domain.register(AccountCommandHandler, part_of=Account)
    test_domain.init(traverse=False)


# ─── Enrich ──────────────────────────────────────────────────────────────


class TestEnrich:
    """Verify that _enrich_command delegates to CommandProcessor.enrich
    and populates metadata correctly."""

    def test_enriched_command_has_stream(self, test_domain):
        identifier = str(uuid4())
        cmd = OpenAccount(account_id=identifier, name="Acme")

        enriched = test_domain._enrich_command(cmd, asynchronous=False)

        assert enriched._metadata.headers.stream is not None
        assert f"command-{identifier}" in enriched._metadata.headers.stream

    def test_enriched_command_has_type(self, test_domain):
        cmd = OpenAccount(account_id=str(uuid4()), name="Acme")

        enriched = test_domain._enrich_command(cmd, asynchronous=False)

        assert enriched._metadata.headers.type == OpenAccount.__type__

    def test_enriched_command_has_domain_kind(self, test_domain):
        cmd = OpenAccount(account_id=str(uuid4()), name="Acme")

        enriched = test_domain._enrich_command(cmd, asynchronous=False)

        assert enriched._metadata.domain.kind == "COMMAND"

    def test_enriched_command_generates_correlation_id(self, test_domain):
        cmd = OpenAccount(account_id=str(uuid4()), name="Acme")

        enriched = test_domain._enrich_command(cmd, asynchronous=False)

        assert enriched._metadata.domain.correlation_id is not None

    def test_enriched_command_uses_provided_correlation_id(self, test_domain):
        cmd = OpenAccount(account_id=str(uuid4()), name="Acme")
        custom_id = "trace-abc-123"

        enriched = test_domain._enrich_command(
            cmd, asynchronous=False, correlation_id=custom_id
        )

        assert enriched._metadata.domain.correlation_id == custom_id


# ─── Process ─────────────────────────────────────────────────────────────


class TestProcess:
    """Verify that domain.process() delegates to CommandProcessor.process."""

    def test_sync_processing_returns_handler_result(self, test_domain):
        identifier = str(uuid4())
        result = test_domain.process(
            OpenAccount(account_id=identifier, name="Acme"),
            asynchronous=False,
        )

        assert result == {"opened": identifier}

    def test_unregistered_command_raises_error(self, test_domain):
        """Processing a command not registered with the domain raises
        ConfigurationError at instantiation time."""

        class UnknownCommand(BaseCommand):
            foo: String()

        with pytest.raises(ConfigurationError, match="should be registered"):
            test_domain.process(UnknownCommand(foo="bar"))


# ─── Handler For ─────────────────────────────────────────────────────────


class TestHandlerFor:
    """Verify that domain.command_handler_for() delegates to
    CommandProcessor.handler_for."""

    def test_returns_correct_handler_class(self, test_domain):
        cmd = OpenAccount(account_id=str(uuid4()), name="Acme")
        handler = test_domain.command_handler_for(cmd)

        assert handler == AccountCommandHandler

    def test_returns_none_for_command_without_handler(self, test_domain):
        handler = test_domain.command_handler_for(CloseAccount())

        assert handler is None
