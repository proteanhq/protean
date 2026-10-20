"""Check what docs/reference/migration/v0-19.md says about upgrading to 0.19."""

import pathlib
import re

from protean.utils.outbox import _CLAIM_ORDER, OUTBOX_INDEXES

PAGE = (
    pathlib.Path(__file__).parents[4] / "docs" / "reference" / "migration" / "v0-19.md"
)


def _active_index():
    return next(ix for ix in OUTBOX_INDEXES if ix.name == "ix_outbox_active")


class TestOutboxClaimOrder:
    def test_the_rebuild_sql_matches_the_declared_index(self):
        index = _active_index()
        expected = ", ".join(
            f"{field} DESC" if field in index.desc else field for field in index.fields
        )

        columns = re.findall(r"ON outbox \(([^)]*)\)", PAGE.read_text())

        assert len(columns) == 4
        assert set(columns) == {expected}

    def test_the_partial_filter_matches_the_declared_index(self):
        statuses = _active_index().where.children[0][1]
        expected = "WHERE status IN ({})".format(
            ", ".join(f"'{status}'" for status in statuses)
        )

        assert PAGE.read_text().count(expected) == 3

    def test_the_listed_claim_order_matches_the_code(self):
        assert _CLAIM_ORDER == ["-priority", "created_at", "sequence_number"]
        text = PAGE.read_text()
        assert "1. `priority`, highest first." in text
        assert "2. `created_at`, oldest first." in text
        assert "3. `sequence_number`, lowest first." in text
