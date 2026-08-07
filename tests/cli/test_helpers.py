"""Unit tests for the CLI optional-dependency helpers (ADR-0029)."""

import pytest
import typer

from protean.cli._helpers import abort_for_missing_dependency
from tests.shared import module_unavailable

pytestmark = pytest.mark.no_test_domain


def test_abort_prints_hint_and_aborts_when_a_package_is_absent(capsys):
    with module_unavailable("fastapi"):
        with pytest.raises(typer.Abort):
            abort_for_missing_dependency(
                "server",
                "'protean observatory'",
                ImportError("no fastapi", name="fastapi"),
            )

    out = capsys.readouterr().out
    assert "'protean observatory'" in out
    assert "fastapi" in out
    assert 'pip install "protean[server]"' in out


def test_abort_catches_a_package_exc_name_never_reports(capsys):
    # jinja2 is part of the server extra, but a missing jinja2 surfaces via
    # starlette with exc.name=None, so an exc.name-based check would miss it.
    # find_spec catches it regardless of how the ImportError was raised.
    with module_unavailable("jinja2"):
        with pytest.raises(typer.Abort):
            abort_for_missing_dependency(
                "server", "'protean observatory'", ImportError("boom")
            )

    out = capsys.readouterr().out
    assert "jinja2" in out
    assert 'pip install "protean[server]"' in out


def test_abort_reraises_when_every_package_is_importable(capsys):
    # fastapi/uvicorn/jinja2 are all installed in the test env, so an ImportError
    # here means a package is present but broken (an incompatible version, a
    # renamed symbol), which names that same package. It is a real bug inside the
    # feature and must surface unchanged, not be relabelled "install the extra".
    exc = ImportError("cannot import name 'X' from 'fastapi'", name="fastapi")

    with pytest.raises(ImportError) as exc_info:
        abort_for_missing_dependency("server", "'protean observatory'", exc)

    assert exc_info.value is exc
    assert "pip install" not in capsys.readouterr().out
