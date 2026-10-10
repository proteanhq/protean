import pytest

from tests.docs.guides.change_state.failing import RepositoryThatFailsAfterAdd


@pytest.fixture
def add_fails(monkeypatch):
    """Make a domain's ``repository_for`` hand out a repository whose ``add()``
    stores the aggregate and then raises."""

    def install(domain):
        real = domain.repository_for
        monkeypatch.setattr(
            domain,
            "repository_for",
            lambda cls: RepositoryThatFailsAfterAdd(real(cls)),
        )

    return install
