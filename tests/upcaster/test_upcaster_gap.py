"""Tests for #1131: the UPCASTER_GAP build-time diagnostic and its
missing-version coverage helper.

An event whose ``__version__`` has outrun its upcasters fails only at *read*
time (a ``DeserializationError`` when an old stored payload is loaded).
``protean check`` now flags it at build time via ``UPCASTER_GAP``.
"""

import pytest

from protean.core.upcaster import BaseUpcaster
from protean.domain import Domain
from protean.fields import String
from protean.utils.upcasting import missing_upcaster_source_versions


class TestMissingUpcasterSourceVersions:
    @pytest.mark.parametrize(
        "edges, current, expected",
        [
            ([], 1, []),  # no prior versions -> nothing to cover
            ([], 2, [1]),  # no upcasters -> v1 stranded
            ([], 3, [1, 2]),  # no upcasters -> v1, v2 stranded
            ([(1, 2), (2, 3)], 3, []),  # full chain -> all covered
            ([(2, 3)], 3, [1]),  # partial -> v1 stranded
            ([(1, 2)], 3, [1, 2]),  # chain stops at v2 -> v1, v2 stranded
            ([(1, 3)], 3, [2]),  # skip-version chain -> v2 stranded
            ([(1, 2), (2, 1)], 3, [1, 2]),  # cyclic edges -> seen-guard, all stranded
        ],
    )
    def test_coverage(self, edges, current, expected):
        assert missing_upcaster_source_versions(edges, current) == expected


@pytest.mark.no_test_domain
class TestUpcasterGapDiagnostic:
    def _gaps(self, domain):
        result = domain.check(traverse=False)
        return [d for d in result["diagnostics"] if d["code"] == "UPCASTER_GAP"]

    def test_zero_upcasters_at_v2_is_a_gap(self):
        domain = Domain(name="GapZero")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order)
        class OrderPlaced:
            __version__ = 2
            name = String()

        gaps = self._gaps(domain)
        assert len(gaps) == 1
        assert gaps[0]["level"] == "warning"
        assert "OrderPlaced" in gaps[0]["element"]
        assert "v1" in gaps[0]["message"]

    def test_partial_coverage_is_a_gap(self):
        domain = Domain(name="GapPartial")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order)
        class OrderPlaced:
            __version__ = 3
            name = String()

        @domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
        class UpcastV2ToV3(BaseUpcaster):
            def upcast(self, data):
                return data

        gaps = self._gaps(domain)
        assert len(gaps) == 1
        # v2 is covered (2->3); v1 is not.
        assert "OrderPlaced" in gaps[0]["element"]
        assert "v1" in gaps[0]["message"]

    def test_full_coverage_is_not_a_gap(self):
        domain = Domain(name="NoGap")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order)
        class OrderPlaced:
            __version__ = 3
            name = String()

        @domain.upcaster(event_type=OrderPlaced, from_version=1, to_version=2)
        class UpcastV1ToV2(BaseUpcaster):
            def upcast(self, data):
                return data

        @domain.upcaster(event_type=OrderPlaced, from_version=2, to_version=3)
        class UpcastV2ToV3(BaseUpcaster):
            def upcast(self, data):
                return data

        assert self._gaps(domain) == []

    def test_v1_event_is_not_a_gap(self):
        domain = Domain(name="V1Only")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order)
        class OrderPlaced:  # default __version__ == 1
            name = String()

        assert self._gaps(domain) == []

    def test_abstract_event_is_not_a_gap(self):
        """An abstract event is a base class with no stored payloads, so it is
        skipped even at version > 1 with no upcaster."""
        domain = Domain(name="AbsGap")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order, abstract=True)
        class BaseOrderEvent:
            __version__ = 2
            name = String()

        assert self._gaps(domain) == []

    def test_string_event_type_upcaster_is_credited(self):
        """A string-named upcaster resolves to its event, so it covers the
        version and produces no false gap."""
        domain = Domain(name="StrCovered")

        @domain.aggregate(is_event_sourced=True)
        class Order:
            name = String()

        @domain.event(part_of=Order)
        class OrderPlaced:
            __version__ = 2
            name = String()

        @domain.upcaster(event_type="OrderPlaced", from_version=1, to_version=2)
        class UpcastV1ToV2(BaseUpcaster):
            def upcast(self, data):
                return data

        assert self._gaps(domain) == []
