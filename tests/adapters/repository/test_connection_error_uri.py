"""The connection error names the database URI without its password."""

import pytest

from protean.adapters.repository import _without_password


@pytest.mark.parametrize(
    ("uri", "shown"),
    [
        (
            "postgresql://shop:s3cret@db.internal:5432/shop",
            "postgresql://shop:***@db.internal:5432/shop",
        ),
        ("postgresql://shop@db.internal/shop", "postgresql://shop@db.internal/shop"),
        ("sqlite:///shop.db", "sqlite:///shop.db"),
        ({"hosts": ["https://elastic:s3cret@es:9200"]}, "<not shown>"),
    ],
)
def test_without_password(uri, shown):
    assert _without_password(uri) == shown
