import nox

PYTHON_VERSIONS = ["3.11", "3.12", "3.13", "3.14"]

# Packages with C extensions that must be rebuilt per Python version.
# Poetry's wheel cache can serve a .so compiled for the wrong interpreter.
_C_EXT_PACKAGES = ["psycopg2"]


def _install(session: nox.Session) -> None:
    """Install the project with all dev/test extras into the nox virtualenv."""
    session.run(
        "poetry",
        "install",
        "--with",
        "dev,test",
        "--all-extras",
        external=True,
    )
    # Force-rebuild C-extension packages so the .so matches this Python version.
    session.run(
        "pip",
        "install",
        "--force-reinstall",
        "--no-cache-dir",
        *_C_EXT_PACKAGES,
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
