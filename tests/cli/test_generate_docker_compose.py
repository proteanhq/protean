"""Regression tests pinning the removal of the ``generate`` command group.

The ``generate docker-compose`` command was a no-op stub (it wrote no file and
ended at a ``# FIXME``); it was removed outright in the 1.0 CLI surface
consolidation (#1113). Real Dockerfile/compose generation is tracked separately
under #397. These tests ensure the command does not silently reappear and that
the ``protean.cli.generate`` module stays inert (a reserved namespace, exposing
no commands and unregistered on the top-level app) until #397 revives it.
"""

import re

from typer.testing import CliRunner

from protean.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def test_generate_group_is_not_registered():
    """`protean generate` is no longer a registered command."""
    result = runner.invoke(app, ["generate"])
    assert result.exit_code != 0
    assert "No such command 'generate'" in _ANSI_RE.sub("", result.output)


def test_generate_docker_compose_command_gone():
    """`protean generate docker-compose` is no longer invocable."""
    result = runner.invoke(app, ["generate", "docker-compose"])
    assert result.exit_code != 0
    assert "No such command 'generate'" in _ANSI_RE.sub("", result.output)


def test_generate_absent_from_top_level_help():
    """The `generate` group does not appear in `protean --help`."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    output = _ANSI_RE.sub("", result.output)
    # Match the command column entry, not the word "Generate" in other
    # commands' descriptions (e.g. schema/docs "Generate ...").
    assert not re.search(r"(?m)^\W*generate\b", output)


def test_generate_module_exposes_no_commands():
    """The reserved `generate` module stays inert — no Typer app, no stub.

    Pins that the module remains an empty placeholder (no ``app`` and no
    ``docker_compose``) so the removed no-op cannot creep back in unregistered.
    """
    import protean.cli.generate as generate_module

    assert not hasattr(generate_module, "app")
    assert not hasattr(generate_module, "docker_compose")
