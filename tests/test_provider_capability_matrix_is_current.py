"""The published capability matrix says what each provider declares in code.

`docs/reference/adapters/database/index.md` is hand-maintained, so a provider
can register, ship, and run in the test matrix without ever reaching the table.
MySQL did: the page introduced the provider in its own section while the matrix
and the entry-point snippet below it still listed five providers.

A reader uses that table to choose a database, so a missing column reads as
"Protean has no MySQL adapter" and a wrong tick reads as a promise. Both are
derived here from the providers themselves.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

import pytest

from protean.port.provider import DatabaseCapabilities, registry

DOCS = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "reference"
    / "adapters"
    / "database"
    / "index.md"
)

pytestmark = pytest.mark.no_test_domain

# Column heading in the matrix for each registered provider name. The matrix is
# written for people, so it uses the product names.
_COLUMN_FOR_PROVIDER = {
    "memory": "Memory",
    "sqlite": "SQLite",
    "postgresql": "PostgreSQL",
    "mssql": "MSSQL",
    "mysql": "MySQL",
    "elasticsearch": "Elasticsearch",
}


def _matrix() -> tuple[list[str], dict[str, list[bool]]]:
    """The published table as (column headings, {capability: [ticked, ...]})."""
    lines = DOCS.read_text(encoding="utf-8").splitlines()
    start = next(
        i for i, line in enumerate(lines) if "Provider Capability Matrix" in line
    )

    header: list[str] | None = None
    rows: dict[str, list[bool]] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            if header is not None:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if header is None:
            header = cells[1:]
            continue
        if set(cells[0]) <= set(":-—| "):  # the alignment row
            continue
        rows[cells[0]] = [bool(cell) for cell in cells[1:]]

    assert header is not None, "no capability matrix found on the page"
    return header, rows


def _provider_names() -> set[str]:
    """Protean's own provider names, from its entry points.

    Read here rather than from ``registry.list()``, which is empty until
    something triggers plugin discovery. A guard that enumerates an empty set
    passes on every page, including a blank one.

    Scoped to the ``protean`` distribution because ``protean.providers`` is a
    public extension point. A third-party provider is not something this page
    documents, and enumerating every installed distribution would fail the
    guard for whoever has one, after importing their plugin to ask.
    """
    return {
        ep.name
        for ep in metadata.distribution("protean").entry_points.select(
            group="protean.providers"
        )
    }


def _declared(provider_name: str) -> DatabaseCapabilities:
    provider_cls = registry.get(provider_name)
    # ``capabilities`` is a property on the class; read it off the descriptor so
    # nothing has to be constructed against a live server.
    return provider_cls.capabilities.fget(provider_cls)  # type: ignore[attr-defined]


def _install_a_third_party_provider(tmp_path, monkeypatch):
    """Put a distribution advertising `protean.providers` on sys.path.

    `protean.providers` is a public extension point, so this is a supported
    thing for someone to have installed. It must not turn a guard about
    Protean's own providers red.
    """
    dist = tmp_path / "acme_protean_db-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: acme-protean-db\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (dist / "entry_points.txt").write_text(
        "[protean.providers]\nacmedb = acme_protean_db:register\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    metadata.MetadataPathFinder.invalidate_caches()


class TestCapabilityMatrix:
    def test_every_registered_provider_has_a_column(self):
        header, _ = _matrix()
        registered = _provider_names()

        missing = sorted(
            name
            for name in registered
            if _COLUMN_FOR_PROVIDER.get(name, name) not in header
        )
        assert not missing, (
            f"No column in the capability matrix for {missing}. A provider can "
            f"ship without reaching this table; MySQL did."
        )

    def test_every_tick_matches_what_the_provider_declares(self):
        header, rows = _matrix()

        for provider_name in sorted(_provider_names()):
            column = _COLUMN_FOR_PROVIDER.get(provider_name, provider_name)
            if column not in header:
                continue  # reported by the test above
            index = header.index(column)
            declared = _declared(provider_name)

            for capability_name, ticks in rows.items():
                flag = getattr(DatabaseCapabilities, capability_name, None)
                if flag is None:
                    continue
                assert ticks[index] == (flag in declared), (
                    f"{column} / {capability_name}: the page says "
                    f"{'yes' if ticks[index] else 'no'}, the provider declares "
                    f"{'yes' if flag in declared else 'no'}."
                )

    def test_every_registered_provider_is_in_the_entry_point_snippet(self):
        """The snippet below the matrix quotes `pyproject.toml`, and drifted the
        same way."""
        page = DOCS.read_text(encoding="utf-8")
        snippet = page.split("### Built-in Entry Points", 1)[1].split("```")[1]

        missing = sorted(
            name for name in _provider_names() if f"\n{name} = " not in snippet
        )
        assert not missing, f"Entry-point snippet does not list {missing}."

    def test_a_third_party_provider_does_not_fail_the_guard(
        self, tmp_path, monkeypatch
    ):
        """Read across every installed distribution, this page would have to
        document everyone's adapters, and asking one for its capabilities would
        import it."""
        _install_a_third_party_provider(tmp_path, monkeypatch)

        assert "acmedb" in {
            ep.name for ep in metadata.entry_points().select(group="protean.providers")
        }
        assert "acmedb" not in _provider_names()

        self.test_every_registered_provider_has_a_column()
        self.test_every_tick_matches_what_the_provider_declares()
        self.test_every_registered_provider_is_in_the_entry_point_snippet()
