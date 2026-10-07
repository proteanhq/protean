"""Run the examples on ``docs/reference/adapters/database/mssql.md``."""

import pytest
from sqlalchemy.dialects import mssql

from protean.exceptions import IncorrectUsageError
from tests.docs.support import load_example
from tests.shared import MSSQL_URI

pytestmark = [pytest.mark.no_test_domain, pytest.mark.mssql]


@pytest.fixture(autouse=True)
def mssql_url(monkeypatch):
    monkeypatch.setenv("MSSQL_URL", MSSQL_URI)


def test_key_column_with_a_length_is_accepted():
    example = load_example("adapters/database/mssql/002.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.User)._database_model
        columns = model.__table__.columns

    assert columns["email"].type.length == 255
    assert columns["email"].unique is True
    # A column with no length is accepted when it is not a key
    assert columns["bio"].type.length is None


def test_key_column_with_no_length_raises():
    example = load_example("adapters/database/mssql/002.py")

    with example.domain.domain_context():
        with pytest.raises(IncorrectUsageError) as exc:
            example.domain.repository_for(example.Coupon)._database_model

    message = str(exc.value)
    assert "Field 'code' on 'Coupon'" in message
    assert "MSSQL requires an explicit max_length" in message


def test_custom_model_uses_mssql_column_types():
    example = load_example("adapters/database/mssql/001.py")

    with example.domain.domain_context():
        model = example.domain.repository_for(example.User)._database_model
        columns = model.__table__.columns

    assert isinstance(columns["name"].type, mssql.NVARCHAR)
    assert columns["name"].type.length == 100
    assert isinstance(columns["email"].type, mssql.NVARCHAR)
    assert columns["email"].type.length == 255
    assert columns["email"].unique is True
    assert not columns["name"].unique
