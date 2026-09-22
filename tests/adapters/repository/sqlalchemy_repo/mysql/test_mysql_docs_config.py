"""Execute the `domain.toml` snippets in the MySQL provider doc.

Nothing in the repo runs the config examples in `docs/`, so a broken one
survives for releases. Three shipped at once in the 0.17.0 audit: a key that
crashed `Domain.init()`, an unquoted `${VAR|default}` that made every generated
project fail to parse its own config, and five keys no adapter reads. A regex
over the text cannot catch "spelled right, nobody reads it", which is exactly
how those got through.

So this reads the fences out of the published page rather than a copy, and runs
each one through `Domain.init()` against a live server. An option renamed in the
code without being renamed in the doc fails here.
"""

import re
from pathlib import Path

import pytest

from protean.adapters.repository.sqlalchemy import MysqlProvider
from protean.domain import Domain
from tests.shared import MARIADB_URI, MYSQL_URI

pytestmark = [pytest.mark.mysql, pytest.mark.no_test_domain]

# tests/adapters/repository/sqlalchemy_repo/mysql/ -> repo root is five up.
DOC = (
    Path(__file__).parents[5]
    / "docs"
    / "reference"
    / "adapters"
    / "database"
    / "mysql.md"
)

# The doc's URIs name an example host that does not exist in CI. Everything else
# in the snippet — the provider name, the option names, the TOML itself — is
# used as published; only the address is repointed at the test server.
LIVE_URI = {
    "mysql+pymysql://": MYSQL_URI,
    "mariadb+pymysql://": MARIADB_URI,
}


def toml_snippets():
    """Every ```toml fence in the doc that configures a database."""
    text = DOC.read_text(encoding="utf-8")
    return [s for s in re.findall(r"```toml\n(.*?)```", text, re.S) if "provider" in s]


def repoint(snippet):
    """Swap the example address for the live test server's.

    Counts the substitution rather than assuming it: if the key were renamed in
    the doc, a silent no-op here would leave the snippet unchanged and the test
    would fail for whatever reason came next, or pass by luck.
    """
    for scheme, uri in LIVE_URI.items():
        if scheme not in snippet:
            continue
        live, count = re.subn(
            r'database_uri = ".*"', f'database_uri = "{uri}"', snippet
        )
        assert count == 1, (
            f"Expected exactly one `database_uri` line to repoint, found "
            f"{count}. The doc's config key may have drifted:\n{snippet}"
        )
        return live, scheme
    raise AssertionError(f"No known URI scheme in snippet:\n{snippet}")


def test_the_doc_still_carries_both_snippets():
    """A page rewrite that drops a snippet would otherwise make the tests below
    pass by testing nothing."""
    schemes = {repoint(s)[1] for s in toml_snippets()}

    assert schemes == set(LIVE_URI)


@pytest.mark.parametrize("snippet", toml_snippets(), ids=["mysql", "mariadb"])
def test_a_documented_config_initializes_a_live_domain(snippet, tmp_path):
    live, scheme = repoint(snippet)
    (tmp_path / "domain.toml").write_text(live, encoding="utf-8")

    domain = Domain(name="DocSnippet", root_path=str(tmp_path / "domain.py"))
    domain.init(traverse=False)

    provider = domain.providers["default"]
    try:
        assert isinstance(provider, MysqlProvider)
        assert provider.is_alive()
        # `mariadb+pymysql://` and `mysql+pymysql://` are one provider under two
        # dialect names, and the doc says which scheme selects which.
        assert provider._engine.dialect.name == (
            "mariadb" if scheme.startswith("mariadb") else "mysql"
        )
    finally:
        provider.close()
