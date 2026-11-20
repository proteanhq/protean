"""The schema migrations guide runs as the page shows.

The dev-box and second-provider command blocks run in order against a SQLite
domain in ``tmp_path``. Each TOML block on the page loads and initializes a
domain. Each ``protean`` command and option the page names is in that
command's ``--help``.
"""

from __future__ import annotations

import re
import shlex
import tomllib

import pytest
from typer.testing import CliRunner

from protean.cli import app
from tests.docs.support import DOCS, DOCS_SRC, domain_from_config, load_example
from tests.support.migrations import PRODUCT_WITH_PRICE, make_project
from tests.support.snippets import expand_includes, extract_toml_blocks

pytestmark = pytest.mark.no_test_domain

PAGE = DOCS / "guides/compose-a-domain/schema-migrations.md"
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
