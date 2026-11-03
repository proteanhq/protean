"""Diagnostics: TestContracts."""

import pytest

from protean import Domain
from protean.ir.builder import IRBuilder
from tests.ir.diagnostics._helpers import (
    build_diagnostics_test_domain,
)


def _empty_domain() -> Domain:
    domain = Domain(name="Test", root_path=".")
    domain.init(traverse=False)
    return domain


class TestContracts:
    """Verify contracts section."""

    @pytest.mark.parametrize(
        "build_domain",
        [build_diagnostics_test_domain, _empty_domain],
        ids=["events-none-published", "empty-domain"],
    )
    def test_contracts_events_empty_when_none_published(self, build_domain):
        """A domain with no ``published=True`` event, including an empty
        domain, has an empty list under ``contracts.events``."""
        ir = IRBuilder(build_domain()).build()
        assert ir["contracts"]["events"] == []
