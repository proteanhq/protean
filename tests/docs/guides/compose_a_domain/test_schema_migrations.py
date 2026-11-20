"""The schema migrations guide runs as the page shows.

The page's command blocks run against a SQLite domain in ``tmp_path``, and
the messages, exit codes and ``alembic.ini`` keys the page quotes match what
the commands print and write. Each TOML block on the page loads and
initializes a domain. Each ``protean`` command and option the page names is in
that command's ``--help``. The page sits in the nav after Configure for
Production, and the pages that create tables link to it.
"""

from __future__ import annotations

import configparser
import re
import shlex
import tomllib

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.docs.support import DOCS, DOCS_SRC, domain_from_config, load_example
from tests.support.migrations import (
    PRODUCT,
    PRODUCT_WITH_PRICE,
    MigrationsProject,
    make_project,
    row_count,
)
from tests.support.snippets import expand_includes, extract_toml_blocks

pytestmark = pytest.mark.no_test_domain

PAGE = DOCS / "guides/compose-a-domain/schema-migrations.md"
PAGE_PATH = "guides/compose-a-domain/schema-migrations.md"
TEXT = PAGE.read_text(encoding="utf-8")
TWO_PROVIDERS = "guides/compose-a-domain/schema-migrations/two_providers.toml"

_BASH_FENCE = re.compile(r"^(?P<indent>[ \t]*)```bash[ \t]*$")
_INLINE_COMMAND = re.compile(r"`(protean [^`]+)`")
_OPTION = re.compile(r"^(--?[A-Za-z][\w-]*)")


def section(heading: str) -> str:
    """The text of the page's ``## <heading>`` section, up to the next one."""
    match = re.search(
        rf"^## {re.escape(heading)}\n(?P<body>.*?)(?=^## |\Z)",
        TEXT,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, f"no section {heading!r} on the page"
    return match.group("body")


def bash_commands(text: str) -> list[list[str]]:
    """The commands in the ``bash`` blocks of ``text``, in order, as tokens."""
    commands = []
    lines = text.splitlines()
    inside = False
    for line in lines:
        if not inside:
            inside = _BASH_FENCE.match(line) is not None
            continue
        stripped = line.strip()
        if stripped.startswith("```"):
            inside = False
        elif stripped and not stripped.startswith("#"):
            commands.append(shlex.split(stripped))
    return commands


def protean_args(tokens: list[str]) -> list[str] | None:
    """The arguments after ``protean``, without leading ``VAR=value`` tokens."""
    while tokens and re.match(r"^[A-Z_]+=", tokens[0]):
        tokens = tokens[1:]
    if not tokens or tokens[0] != "protean":
        return None
    return tokens[1:]


def sqlite_db(name: str) -> dict[str, str]:
    return {"provider": "sqlite", "database_uri": f"sqlite:///{name}"}


def only_command(heading: str, program: str) -> list[str]:
    """The tokens of the single ``program`` command in a section's bash blocks."""
    commands = [
        tokens
        for tokens in bash_commands(section(heading))
        if tokens and tokens[0] == program
    ]
    assert len(commands) == 1, commands
    return commands[0]


def first_revision(project: MigrationsProject) -> str:
    versions = project.versions()
    assert versions
    match = re.search(
        r"^revision(?:: str)? = ['\"](\w+)['\"]",
        versions[0].read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match is not None
    return match.group(1)


@pytest.mark.sqlite
def test_dev_box_commands_run_in_order(tmp_path, monkeypatch):
    commands = [
        protean_args(tokens)
        for tokens in bash_commands(section("Change a table on the dev box"))
    ]
    assert [args[:2] for args in commands if args] == [
        ["db", "init"],
        ["db", "migrate"],
        ["db", "upgrade"],
    ]
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("shop.db")})
    project.write(PRODUCT_WITH_PRICE)

    for args in commands:
        assert args is not None
        result = project.invoke(*args)
        assert result.exit_code == 0, f"{args}: {result.output}"
        if args[1] == "migrate":
            assert len(project.versions()) == 1

    result = project.run("check")
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == "The database matches the table definitions."

    no_change = re.search(r"prints `(No changes detected[^`]*)`", TEXT)
    assert no_change is not None
    result = project.run("migrate", "-m", "nothing")
    assert result.exit_code == 0, result.output
    assert no_change.group(1) in result.output
    assert len(project.versions()) == 1


def exit_code_table() -> dict[int, str]:
    rows = re.findall(r"^\| `(\d)` \| (.+?) \|$", TEXT, re.MULTILINE)
    return {int(code): meaning for code, meaning in rows}


@pytest.mark.sqlite
def test_check_exit_codes_match_the_table(tmp_path, monkeypatch):
    assert set(exit_code_table()) == {0, 1, 2}
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("shop.db")})
    project.write(PRODUCT)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")
    assert project.run("check").exit_code == 0

    project.write(PRODUCT_WITH_PRICE)
    differs = project.run("check")
    assert differs.exit_code == 1
    assert "price" in differs.stdout

    unusable = project.run("check", "--directory=nosuch")
    assert unusable.exit_code == 2
    assert unusable.stdout == ""
    assert "nosuch" in unusable.stderr


@pytest.mark.sqlite
def test_empty_migration_command_writes_a_file(tmp_path, monkeypatch):
    tokens = only_command("Know what autogenerate cannot do", "alembic")
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("shop.db")})
    project.write(PRODUCT)
    project.run_ok("init")

    project.alembic(*tokens[1:])

    versions = project.versions()
    assert len(versions) == 1
    message = tokens[tokens.index("-m") + 1]
    assert message in versions[0].read_text(encoding="utf-8")


@pytest.mark.sqlite
def test_sql_range_prints_only_the_pending_migration(tmp_path, monkeypatch):
    sql_commands = [
        tokens
        for tokens in bash_commands(section("Apply migrations to production"))
        if "--sql" in tokens
    ]
    assert len(sql_commands) == 1, sql_commands
    # Offline SQL takes its dialect from the configured provider.
    assert sql_commands[0][0] == "PROTEAN_ENV=production"
    args = protean_args(sql_commands[0])
    assert args is not None
    args = args[: args.index(">")] if ">" in args else args
    assert args[:2] == ["db", "upgrade"]
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("shop.db")})
    project.write(PRODUCT)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("upgrade")
    current = first_revision(project)
    project.write(PRODUCT_WITH_PRICE)
    project.run_ok("migrate", "-m", "add price")

    ranged = project.invoke(
        *[arg.replace("<current>", current) for arg in args], "--domain", "domain.py"
    )

    assert ranged.exit_code == 0, ranged.output
    assert "ADD COLUMN price" in ranged.stdout
    assert "UPDATE alembic_version" in ranged.stdout
    assert "CREATE TABLE" not in ranged.stdout

    # Without the range, the script is for an empty database, as the page says.
    unranged = project.run("upgrade", "--sql")
    assert unranged.exit_code == 0, unranged.output
    assert "CREATE TABLE product" in unranged.stdout


@pytest.mark.sqlite
def test_stamp_head_adopts_an_existing_database(tmp_path, monkeypatch):
    tokens = only_command("Adopt migrations on an existing database", "alembic")
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("prod.db")})
    project.write(PRODUCT_WITH_PRICE)
    project.run_ok("setup")
    project.add_products("Lamp")

    project.databases = {"default": sqlite_db("dev.db")}
    project.write(PRODUCT_WITH_PRICE)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial schema")

    project.databases = {"default": sqlite_db("prod.db")}
    project.write(PRODUCT_WITH_PRICE)
    project.alembic(*tokens[1:])

    project.run_ok("check")
    result = project.run_ok("upgrade")
    assert "already exists" not in result.output
    assert row_count(f"sqlite:///{tmp_path / 'prod.db'}", "product") == 1


@pytest.mark.sqlite
def test_setup_then_upgrade_on_one_database_fails(tmp_path, monkeypatch):
    assert "Do not mix `protean db setup` and migrations" in TEXT
    project = make_project(tmp_path, monkeypatch, {"default": sqlite_db("shop.db")})
    project.write(PRODUCT)
    project.run_ok("init")
    project.run_ok("migrate", "-m", "initial")
    project.run_ok("setup")

    result = project.run("upgrade")

    assert result.exit_code != 0
    assert "already exists" in result.output


@pytest.mark.sqlite
def test_second_provider_commands_run_in_order(tmp_path, monkeypatch):
    commands = [
        protean_args(tokens)
        for tokens in bash_commands(section("Give each provider its own folder"))
    ]
    assert [args[:2] for args in commands if args] == [
        ["db", "init"],
        ["db", "migrate"],
        ["db", "upgrade"],
    ]
    project = make_project(
        tmp_path,
        monkeypatch,
        {"default": sqlite_db("shop.db"), "reporting": sqlite_db("reporting.db")},
    )
    project.write(
        """
@domain.aggregate(database="reporting")
class DailySales:
    total = Integer()
"""
    )

    for args in commands:
        assert args is not None
        result = project.invoke(*args)
        assert result.exit_code == 0, f"{args}: {result.output}"

    versions = sorted((tmp_path / "migrations/reporting/versions").glob("*.py"))
    assert len(versions) == 1
    result = project.run("check", "--directory=migrations/reporting")
    assert result.exit_code == 0, result.output

    written = configparser.RawConfigParser()
    written.read(tmp_path / "migrations/reporting/alembic.ini", encoding="utf-8")
    shown = ini_keys(section("Give each provider its own folder"))
    assert set(shown) == {"protean_domain", "protean_provider", "protean_root"}
    for key, value in shown.items():
        assert written.get("alembic", key) == value


def ini_keys(text: str) -> dict[str, str]:
    """The ``key = value`` lines of the single ``ini`` block in ``text``."""
    blocks = re.findall(r"^```ini\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    assert len(blocks) == 1
    pairs = [
        line.split("=", 1)
        for line in blocks[0].splitlines()
        if line.strip() and not line.startswith("#")
    ]
    return {key.strip(): value.strip() for key, value in pairs}


def toml_blocks() -> list[str]:
    expanded = expand_includes(TEXT, [DOCS_SRC])
    return [
        block.source for block in extract_toml_blocks(expanded) if not block.fragment
    ]


def test_page_has_a_toml_block_with_databases():
    configs = [tomllib.loads(source) for source in toml_blocks()]

    assert any("databases" in config for config in configs)


@pytest.mark.sqlite
@pytest.mark.parametrize("source", toml_blocks())
def test_toml_block_initializes_a_domain(source, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REPORTING_DATABASE_URL", raising=False)
    domain = domain_from_config(TWO_PROVIDERS, tmp_path, text=source)

    configured = tomllib.loads(source)["databases"]
    assert configured

    domain.init(traverse=False)
    try:
        for name, settings in configured.items():
            assert domain.databases[name].config["provider"] == settings["provider"]
    finally:
        domain.close()


def page_commands() -> list[list[str]]:
    """Every ``protean`` command on the page, from code blocks and inline code."""
    token_lists = bash_commands(TEXT) + [
        shlex.split(match) for match in _INLINE_COMMAND.findall(TEXT)
    ]
    return [args for args in map(protean_args, token_lists) if args]


def command_options() -> list[tuple[str, str]]:
    """Each (command, option) pair the page names, and each command with ``""``."""
    pairs = set()
    for args in page_commands():
        command = args[:2] if args[0] == "db" else args[:1]
        pairs.add((" ".join(command), ""))
        for token in args[len(command) :]:
            match = _OPTION.match(token)
            if match:
                pairs.add((" ".join(command), match.group(1)))
    return sorted(pairs)


COMMAND_OPTIONS = command_options()


def test_page_names_every_migration_command():
    commands = {command for command, _ in COMMAND_OPTIONS}

    assert {
        "db init",
        "db migrate",
        "db upgrade",
        "db downgrade",
        "db check",
        "upgrade-check",
    } <= commands
    assert ("db upgrade", "--sql") in COMMAND_OPTIONS
    assert ("db init", "--provider") in COMMAND_OPTIONS


@pytest.mark.parametrize(
    ("command", "option"),
    COMMAND_OPTIONS,
    ids=[f"{command} {option}".strip() for command, option in COMMAND_OPTIONS],
)
def test_command_help_lists_the_option(command, option):
    result = CliRunner().invoke(app, [*command.split(), "--help"])

    assert result.exit_code == 0, result.output
    # A whole-word match, so ``--dir`` does not pass on ``--directory``.
    assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", result.output)


@pytest.mark.sqlite
def test_metadata_example_lists_the_product_table():
    example = load_example("guides/compose-a-domain/schema-migrations/001.py")

    assert example.tables == {"product": ["_version", "id", "name", "price"]}


def test_page_follows_production_configuration_in_the_nav():
    nav = [
        line.strip()
        for line in (DOCS.parent / "mkdocs.yml")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip().startswith("- guides/compose-a-domain/")
    ]
    position = nav.index(f"- {PAGE_PATH}")

    assert nav[position - 1] == "- guides/compose-a-domain/production-configuration.md"


def test_autogenerate_limits_come_before_production():
    limits = TEXT.index("\n## Know what autogenerate cannot do\n")
    production = TEXT.index("\n## Apply migrations to production\n")

    assert limits < production


@pytest.mark.parametrize(
    "page",
    [
        "guides/compose-a-domain/production-configuration.md",
        "reference/cli/data/database.md",
        "guides/domain-definition/indexes.md",
        "patterns/index-aggregates-for-query-paths.md",
        "guides/server/outbox.md",
        "guides/consume-state/projectors.md",
        "guides/consume-state/subscribers.md",
    ],
)
def test_page_links_to_the_guide(page):
    text = (DOCS / page).read_text(encoding="utf-8")

    assert re.search(r"\]\(([^)\s]*/)?schema-migrations\.md[)#]", text)
