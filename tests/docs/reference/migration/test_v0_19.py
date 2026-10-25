"""Check what docs/reference/migration/v0-19.md says about upgrading to 0.19."""

import pathlib
import re

import pytest

from protean.adapters.repository.sqlalchemy import render_index_ddl
from protean.domain import Domain
from protean.utils.outbox import _CLAIM_ORDER, OUTBOX_INDEXES

pytestmark = pytest.mark.no_test_domain

PAGE = (
    pathlib.Path(__file__).parents[4] / "docs" / "reference" / "migration" / "v0-19.md"
)


def _active_index():
    return next(ix for ix in OUTBOX_INDEXES if ix.name == "ix_outbox_active")


def _tab_statements() -> dict[str, list[str]]:
    """The ``CREATE INDEX`` statements under each tab of the rebuild section."""
    tabs = re.split(r'^=== "([^"]+)"$', PAGE.read_text(), flags=re.MULTILINE)
    return {
        label: [
            " ".join(statement.split())
            for statement in re.findall(r"(CREATE INDEX[^;]*);", body)
        ]
        for label, body in zip(tabs[1::2], tabs[2::2], strict=True)
    }


@pytest.fixture(scope="module")
def outbox_entity():
    domain = Domain(name="MigrationDocs")
    domain.config["enable_outbox"] = True
    domain.config["server"]["default_subscription_type"] = "stream"
    domain.init(traverse=False)
    with domain.domain_context():
        yield domain._get_outbox_repo("default").meta_.part_of


TABS = {
    "PostgreSQL": ["postgresql"],
    "SQLite": ["sqlite"],
    "SQL Server (full index)": ["mssql"],
    "MySQL / MariaDB (full index)": ["mysql", "mariadb"],
}


class TestOutboxClaimOrder:
    def test_every_tab_matches_the_ddl_protean_renders(self, outbox_entity):
        statements = _tab_statements()
        assert set(statements) == set(TABS)

        for label, dialects in TABS.items():
            for dialect in dialects:
                rendered = [
                    ddl
                    for ddl in render_index_ddl(outbox_entity, dialect)
                    if "ix_outbox_active" in ddl
                ]
                assert len(rendered) == 1
                assert statements[label] == rendered, (label, dialect)

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

        assert PAGE.read_text().count(expected) == 2

    def test_the_listed_claim_order_matches_the_code(self):
        assert _CLAIM_ORDER == ["-priority", "created_at", "sequence_number", "id"]
        text = PAGE.read_text()
        assert "1. `priority`, highest first." in text
        assert "2. `created_at`, oldest first." in text
        assert "3. `sequence_number`, lowest first." in text
        assert "4. `id`, lowest first." in text
