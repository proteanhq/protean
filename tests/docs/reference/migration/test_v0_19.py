"""Check what docs/reference/migration/v0-19.md says about upgrading to 0.19."""

import pathlib
import re
from datetime import UTC, datetime

import pytest

from protean.adapters.repository.sqlalchemy import render_index_ddl
from protean.domain import Domain
from protean.utils.eventing import DomainMeta, MessageHeaders, Metadata
from protean.utils.outbox import _CLAIM_ORDER, OUTBOX_INDEXES, Outbox, OutboxStatus
from protean.utils.reflection import fields
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain

PAGE = (
    pathlib.Path(__file__).parents[4] / "docs" / "reference" / "migration" / "v0-19.md"
)


def _active_index():
    return next(ix for ix in OUTBOX_INDEXES if ix.name == "ix_outbox_active")


def _hold_back_index():
    return next(ix for ix in OUTBOX_INDEXES if ix.name == "ix_outbox_hold_back")


def _section(heading: str) -> str:
    """The text under ``heading``, up to the next heading or rule."""
    text = PAGE.read_text()
    start = text.index(f"\n{heading}\n") + len(heading) + 2
    end = re.compile(r"^(#|---)", flags=re.MULTILINE).search(text, start)
    return text[start : end.start() if end else len(text)]


REBUILD = "### Rebuild `ix_outbox_active`"
ADD_COLUMN = "### Add the `stream_category` column"
BACKFILL = "### Rows already in the outbox"


def _tab_statements(heading: str = REBUILD) -> dict[str, list[str]]:
    """The ``CREATE INDEX`` statements under each tab of a section."""
    tabs = re.split(r'^=== "([^"]+)"$', _section(heading), flags=re.MULTILINE)
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

        columns = re.findall(r"ON outbox \(([^)]*)\)", _section(REBUILD))

        assert len(columns) == 4
        assert set(columns) == {expected}

    def test_the_partial_filter_matches_the_declared_index(self):
        statuses = _active_index().where.children[0][1]
        expected = "WHERE status IN ({})".format(
            ", ".join(f"'{status}'" for status in statuses)
        )

        assert _section(REBUILD).count(expected) == 2

    def test_the_listed_claim_order_matches_the_code(self):
        assert _CLAIM_ORDER == ["-priority", "created_at", "sequence_number", "id"]
        text = PAGE.read_text()
        assert "1. `priority`, highest first." in text
        assert "2. `created_at`, oldest first." in text
        assert "3. `sequence_number`, lowest first." in text
        assert "4. `id`, lowest first." in text


HOLD_BACK_TABS = {
    "PostgreSQL": ["postgresql"],
    "SQLite": ["sqlite"],
    "SQL Server": ["mssql"],
    "MySQL / MariaDB": ["mysql", "mariadb"],
}


class TestOutboxHoldBack:
    def test_every_tab_creates_the_index_protean_renders(self, outbox_entity):
        statements = _tab_statements(ADD_COLUMN)
        assert set(statements) == set(HOLD_BACK_TABS)

        for label, dialects in HOLD_BACK_TABS.items():
            for dialect in dialects:
                rendered = [
                    ddl
                    for ddl in render_index_ddl(outbox_entity, dialect)
                    if "ix_outbox_hold_back" in ddl
                ]
                assert len(rendered) == 1
                assert statements[label] == rendered, (label, dialect)

    def test_every_tab_adds_the_declared_column(self, outbox_entity):
        max_length = fields(outbox_entity)["stream_category"].max_length
        tabs = re.split(r'^=== "([^"]+)"$', _section(ADD_COLUMN), flags=re.MULTILINE)
        bodies = dict(zip(tabs[1::2], tabs[2::2], strict=True))
        assert set(bodies) == set(HOLD_BACK_TABS)

        for label, body in bodies.items():
            assert re.search(
                rf"ALTER TABLE outbox ADD (COLUMN )?stream_category "
                rf"VARCHAR\({max_length}\);",
                body,
            ), label

    def test_the_index_columns_match_the_declared_index(self):
        expected = ", ".join(_hold_back_index().fields)

        columns = re.findall(r"ON outbox \(([^)]*)\)", _section(ADD_COLUMN))

        assert len(columns) == 4
        assert set(columns) == {expected}


def _outbox_row(minute, label, partition_key, category, status=OutboxStatus.PENDING):
    metadata = Metadata(
        headers=MessageHeaders(id=label, type="Shop.Placed.v1", stream="shop::order"),
        domain=DomainMeta(stream_category=category) if category else None,
    )
    row = Outbox.create_message(
        message_id=label,
        stream_name="shop::order-1",
        message_type="Shop.Placed.v1",
        data={},
        metadata=metadata,
        partition_key=partition_key,
    )
    row.created_at = datetime(2026, 1, 1, 0, minute, tzinfo=UTC)
    row.status = status.value
    return row


class TestFillStreamCategory:
    def test_fills_unpublished_partitioned_rows_from_their_metadata(self):
        example = load_example("reference/migration/v0-19/001.py")
        example.domain.init(traverse=False)

        with example.domain.domain_context():
            repo = example.domain._get_outbox_repo("default")
            # "a-no-domain" sorts first, so the later pages must step past it.
            for row in [
                _outbox_row(0, "a-no-domain", "acme", None),
                _outbox_row(1, "b-pending", "acme", "shop::order"),
                _outbox_row(
                    2, "c-abandoned", "acme", "shop::order", OutboxStatus.ABANDONED
                ),
                _outbox_row(
                    3, "d-published", "acme", "shop::order", OutboxStatus.PUBLISHED
                ),
                _outbox_row(4, "e-unpartitioned", None, "shop::order"),
            ]:
                repo.add(row)

        assert example.fill_stream_category(page_size=1) == 2

        with example.domain.domain_context():
            rows = example.domain._get_outbox_repo("default").query.all().items
            categories = {row.message_id: row.stream_category for row in rows}

        assert categories == {
            "a-no-domain": None,
            "b-pending": "shop::order",
            "c-abandoned": "shop::order",
            "d-published": None,
            "e-unpartitioned": None,
        }

    def test_the_page_shows_the_fill_snippet(self):
        assert '--8<-- "reference/migration/v0-19/001.py:fill"' in _section(BACKFILL)
