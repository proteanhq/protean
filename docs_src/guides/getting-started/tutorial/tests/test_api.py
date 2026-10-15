# --8<-- [start:full]
from bookshelf.api import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_add_book_endpoint():
    response = client.post(
        "/books",
        json={
            "title": "The Great Gatsby",
            "author": "F. Scott Fitzgerald",
            "price_amount": 12.99,
        },
    )
    assert response.status_code == 200
    assert "book_id" in response.json()


def test_browse_catalog():
    # Add a book first
    client.post(
        "/books",
        json={
            "title": "Dune",
            "author": "Frank Herbert",
            "price_amount": 15.99,
        },
    )

    response = client.get("/catalog")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1


def test_book_not_found():
    response = client.get("/catalog/nonexistent-id")
    assert response.status_code == 404


# --8<-- [end:full]
