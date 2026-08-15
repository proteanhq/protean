import nox

# Skip a version whose interpreter is not installed instead of failing the run.
# 3.15 is a prerelease many contributors will not have locally, and Nox otherwise
# errors on a missing interpreter when it detects a CI environment. Protean's CI
# does not run Nox (it uses the GitHub Actions matrix directly), so this only
# affects local `make test-matrix`, which should skip what is not installed.
nox.options.error_on_missing_interpreters = False

PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14", "3.15"]

# Packages with C extensions that must be rebuilt per Python version.
# uv's wheel cache can serve a .so compiled for the wrong interpreter.
_C_EXT_PACKAGES = ["psycopg2-binary"]


def _install(session: nox.Session) -> None:
    """Install the project with all dev/test extras into the nox session venv."""
    # Use --python to point uv sync at the nox session's interpreter,
    # ensuring dependencies land in the session venv (not the project .venv).
    session.run(
        "uv",
        "sync",
        "--python",
        str(session.virtualenv.location),
        "--group",
        "dev",
        "--group",
        "test",
        "--all-extras",
        external=True,
    )
    # Force-rebuild C-extension packages so the .so matches this Python version.
    session.run(
        "uv",
        "pip",
        "install",
        "--python",
        str(session.virtualenv.location),
        "--reinstall",
        *_C_EXT_PACKAGES,
        external=True,
    )


@nox.session(python=PYTHON_VERSIONS)
def tests(session: nox.Session) -> None:
    """Run core tests across Python versions."""
    _install(session)
    session.run("protean", "test")


@nox.session(python=PYTHON_VERSIONS)
def full(session: nox.Session) -> None:
    """Run full test suite (all adapters) across Python versions."""
    _install(session)
    session.run("protean", "test", "-c", "FULL")
