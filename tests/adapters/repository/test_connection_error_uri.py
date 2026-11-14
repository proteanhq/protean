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
        (
            "postgresql://shop@db.internal/shop?password=s3cret",
            "postgresql://shop@db.internal/shop",
        ),
        (
            "postgresql://shop:s3/cret@db.internal/shop",
            "postgresql://shop:***@db.internal/shop",
        ),
        (
            "postgresql://shop:s3?cr#et@db.internal/shop",
            "postgresql://shop:***@db.internal/shop",
        ),
        (
            "postgresql://db.internal/shop?password=s3cret@x",
            "postgresql://db.internal/shop",
        ),
        (
            "postgresql://shop@db.internal/shop?password=s3cret@x",
            "postgresql://shop@db.internal/shop",
        ),
        (
            "postgresql://shop:s3@cret@db.internal/shop",
            "postgresql://shop:***@db.internal/shop",
        ),
        ("not a uri", "<not shown>"),
        ({"hosts": ["https://elastic:s3cret@es:9200"]}, "<not shown>"),
    ],
)
def test_without_password(uri, shown):
    assert _without_password(uri) == shown
