"""Unit tests for the CLI optional-dependency helpers (ADR-0029)."""

import pytest
import typer

from protean.cli._helpers import abort_for_missing_dependency


def test_abort_prints_hint_and_aborts_for_a_known_missing_package(capsys):
    exc = ImportError("No module named 'fastapi'", name="fastapi")

    with pytest.raises(typer.Abort):
        abort_for_missing_dependency(
            "server", "'protean observatory'", ("fastapi", "uvicorn"), exc
        )

    out = capsys.readouterr().out
    assert "'protean observatory'" in out
    assert "fastapi" in out
    assert 'pip install "protean[server]"' in out


def test_abort_names_the_actually_missing_package(capsys):
    # The stack lists several packages; the message names the one that failed.
    exc = ImportError("No module named 'uvicorn'", name="uvicorn")

    with pytest.raises(typer.Abort):
        abort_for_missing_dependency(
            "server", "'protean observatory'", ("fastapi", "uvicorn", "jinja2"), exc
        )

    assert "uvicorn" in capsys.readouterr().out


def test_abort_reraises_an_unrelated_import_error(capsys):
    # A missing module that is NOT part of the feature's stack is a real bug and
    # must surface unchanged, not be relabelled as a missing extra.
    exc = ImportError("No module named 'yaml'", name="yaml")

    with pytest.raises(ImportError) as exc_info:
        abort_for_missing_dependency("server", "'x'", ("fastapi",), exc)

    assert exc_info.value is exc
    assert "pip install" not in capsys.readouterr().out
