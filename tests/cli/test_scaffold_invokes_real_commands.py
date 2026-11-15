"""The generated project may only call CLI commands that exist.

`protean generate docker` sat in the scaffold's Makefile after the `generate`
group was removed in this release, so `make generate-docker` in a freshly
generated project answered `No such command 'generate'`. The template tests
initialise the domain but never look at what the Makefile invokes, and a
Makefile target is not Python, so nothing else noticed either.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.main import get_command

from protean.cli import app
from protean.scaffold import create_project

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "protean"
    / "template"
    / "domain_template"
)

pytestmark = pytest.mark.no_test_domain


def _real_commands() -> set[str]:
    return set(get_command(app).commands)


def _invoked_commands(text: str) -> set[str]:
    """Every `protean <word>` the file runs, ignoring flags."""
    return {
        m.group(1)
        for m in re.finditer(r"\bprotean\s+([a-z][a-z0-9-]*)", text)
        if not m.group(1).startswith("-")
    }


def _make_targets(text: str) -> set[str]:
    """Targets the Makefile actually defines."""
    return set(re.findall(r"(?m)^([a-zA-Z][\w-]*):", text))


def _make_invocations(text: str) -> set[str]:
    """Every `make <target>` the README tells a reader to run."""
    return set(re.findall(r"\bmake\s+([a-z][\w-]*)", text))


# The Makefile and README render per database, and only the SQL databases get
# the `db-*` targets, so each check runs against a rendered project.
DATABASES = [
    pytest.param("memory", id="memory database"),
    pytest.param("sqlite", id="sqlite database"),
    pytest.param("postgresql", id="postgresql database"),
]


def _render(tmp_path: Path, database: str) -> Path:
    create_project(
        "shop",
        output_folder=str(tmp_path),
        data={"database": database},
        defaults=True,
    )
    return tmp_path / "shop"


class TestScaffoldCommandsExist:
    def test_the_template_is_where_we_think(self):
        assert (TEMPLATE / "Makefile.jinja").is_file(), (
            f"{TEMPLATE}/Makefile.jinja is missing"
        )
        assert (TEMPLATE / "README.md.jinja").is_file(), "template README is missing"
        assert _real_commands(), "no CLI commands discovered; the app moved"

    @pytest.mark.parametrize("database", DATABASES)
    def test_the_makefile_only_runs_commands_the_cli_has(self, tmp_path, database):
        project = _render(tmp_path, database)
        invoked = _invoked_commands((project / "Makefile").read_text(encoding="utf-8"))
        assert invoked, "parsed no `protean <cmd>` from the Makefile; check the regex"

        missing = sorted(invoked - _real_commands())
        assert not missing, (
            "The generated project's Makefile runs commands the CLI does not "
            f"have, so those targets fail for every new project: {missing}. "
            f"Available: {sorted(_real_commands())}"
        )

    def test_the_db_targets_run_db_subcommands_the_cli_has(self, tmp_path):
        """`protean db <sub>` must exist too, not only the `db` group."""
        makefile = (_render(tmp_path, "sqlite") / "Makefile").read_text(
            encoding="utf-8"
        )
        invoked = set(re.findall(r"\bprotean\s+db\s+([a-z][a-z0-9-]*)", makefile))
        assert invoked == {"migrate", "upgrade", "check"}

        db_group = get_command(app).commands["db"]
        assert invoked <= set(db_group.commands)

    @pytest.mark.parametrize("database", DATABASES)
    def test_the_readme_only_points_at_targets_the_makefile_defines(
        self, tmp_path, database
    ):
        """The README is how a reader finds the targets, so it drifts the same way."""
        project = _render(tmp_path, database)
        readme = (project / "README.md").read_text(encoding="utf-8")
        makefile = (project / "Makefile").read_text(encoding="utf-8")

        referenced = _make_invocations(readme)
        assert referenced, "parsed no `make <target>` from the README; check the regex"

        missing = sorted(referenced - _make_targets(makefile))
        assert not missing, (
            "The generated README tells a reader to run targets the generated "
            f"Makefile does not define: {missing}"
        )
