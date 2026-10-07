"""Run the example on ``docs/reference/adapters/database/sqlite.md``."""

import pytest
import sqlalchemy as sa

from tests.docs.support import load_example

pytestmark = [pytest.mark.no_test_domain, pytest.mark.sqlite]


def test_custom_model_uses_its_own_columns(monkeypatch, tmp_path):
    # The example writes test.db to the working directory
    monkeypatch.chdir(tmp_path)
    example = load_example("adapters/database/sqlite/001.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.User)._database_model
        columns = model.__table__.columns

    assert isinstance(columns["name"].type, sa.String)
    assert columns["name"].type.length == 100
    assert columns["email"].type.length == 255
    assert columns["email"].unique is True
    assert not columns["name"].unique
