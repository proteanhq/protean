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
    and system git config and the caller's git ignore file, and sets a fixed
    author and committer.
    """
    # Git exports GIT_DIR and GIT_INDEX_FILE to its hooks. A test run from a
    # pre-commit hook would otherwise stage files in the outer repository, and
    # a global hooks path or signing key would fail the test's own commits.
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    # Git reads $XDG_CONFIG_HOME/git/ignore even without a global config, and
    # `git add` fails on a path that file ignores.
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.excludesFile")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", os.devnull)
    for key, value in _GIT_IDENTITY.items():
        monkeypatch.setenv(key, value)
