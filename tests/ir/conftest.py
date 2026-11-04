"""Fixtures shared by the IR tests."""

import os

import pytest

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@test.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@test.com",
}


@pytest.fixture
def isolated_git(monkeypatch):
    """Run every git command in the test without the caller's git setup.

    This covers the test's own git commands and the ones the code under test
    starts. The fixture removes every ``GIT_*`` variable, ignores the global
    and system git config, and sets a fixed author and committer.
    """
    # Git exports GIT_DIR and GIT_INDEX_FILE to its hooks. A test run from a
    # pre-commit hook would otherwise stage files in the outer repository, and
    # a global hooks path or signing key would fail the test's own commits.
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key, value in _GIT_IDENTITY.items():
        monkeypatch.setenv(key, value)
