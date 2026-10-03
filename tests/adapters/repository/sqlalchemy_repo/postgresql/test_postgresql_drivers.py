"""Both supported PostgreSQL drivers connect to a live server."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine.url import make_url

from protean.adapters.repository.sqlalchemy import PostgresqlProvider
from tests.shared import POSTGRES_URI


@pytest.mark.postgresql
@pytest.mark.parametrize("driver", ["psycopg", "psycopg2"])
def test_driver_connects_and_queries(test_domain, driver):
    uri = make_url(POSTGRES_URI).set(drivername=f"postgresql+{driver}")
    provider = PostgresqlProvider(
        name="driver_check",
        domain=test_domain,
        conn_info={
            "provider": "postgresql",
            "database_uri": uri.render_as_string(hide_password=False),
        },
    )
    try:
        assert provider._engine.dialect.driver == driver
        assert provider.is_alive()
        with provider._engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        provider.close()
