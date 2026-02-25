# Chapter 10: Exposing the Domain Through an API

Our domain logic works and the project is organized — but nobody can use
the bookstore yet. In this chapter we will build a FastAPI web layer
that translates HTTP requests into domain commands and projection
queries.

!!! note "Thin Endpoints"
    API endpoints are **thin adapters** at the boundary of the domain.
    They translate HTTP requests into commands, hand them to
    `domain.process()`, and translate the results back to HTTP responses.
    All business logic stays in the domain layer.

## Setting Up FastAPI

Install FastAPI and Uvicorn:

```shell
pip install fastapi uvicorn
```

Create `bookshelf/api.py`:

```python
--8<-- "guides/getting-started/tutorial/ch10.py:app_setup"
```

`DomainContextMiddleware` ensures every request runs inside the correct
domain context. `register_exception_handlers()` maps domain exceptions
(like `ObjectNotFoundError`, `ValidationError`) to standard HTTP error
responses (404, 400, etc.).

## Write Endpoints — Commands

Each write endpoint translates an HTTP request into a command and
dispatches it:

```python
--8<-- "guides/getting-started/tutorial/ch10.py:write_endpoints"
```

The pattern is always the same:

1. Accept a Pydantic request model.
2. Build a domain command from the request data.
3. Call `domain.process(command)`.
4. Return the result.

## Read Endpoints — Querying Projections

Read endpoints query projections using `domain.view_for()`, which
returns a `ReadView` — the read-side entry point for projections:

```python
--8<-- "guides/getting-started/tutorial/ch10.py:read_endpoints"
```

`domain.view_for(BookCatalog)` returns a `ReadView` with `get()` for
single-record lookups, `query` for a `ReadOnlyQuerySet` (filtering,
sorting, pagination), `find_by()`, `count()`, and `exists()`. All
mutation operations are blocked.

## Running the API

Start the server:

```shell
$ uvicorn bookshelf.api:app --reload
INFO:     Uvicorn running on http://127.0.0.1:8000
```

Test it with `curl`:

```shell
# Add a book
$ curl -X POST http://localhost:8000/books \
  -H "Content-Type: application/json" \
  -d '{"title": "The Great Gatsby", "author": "F. Scott Fitzgerald", "price_amount": 12.99}'

{"book_id": "a3b2c1d0-..."}

# Browse the catalog
$ curl http://localhost:8000/catalog

{"entries": [{"book_id": "a3b2c1d0-...", "title": "The Great Gatsby", ...}], "total": 1}

# Place an order
$ curl -X POST http://localhost:8000/orders \
  -H "Content-Type: application/json" \
  -d '{"customer_name": "Alice", "book_title": "The Great Gatsby", "quantity": 1, "unit_price_amount": 12.99}'

{"order_id": "e5f6g7h8-..."}
```

Visit `http://localhost:8000/docs` for the interactive Swagger
documentation that FastAPI generates automatically.

## What We Built

- A **FastAPI application** with `DomainContextMiddleware` and automatic
  error handling.
- **Write endpoints** that translate HTTP requests into domain commands.
- **Read endpoints** that query projections with `domain.view_for()`.
- A running **web server** that exposes the bookstore over HTTP.

In the next chapter, we will add tests for everything we have built so
far — domain logic, command flows, and API endpoints.

## Full Source

```python
--8<-- "guides/getting-started/tutorial/ch10.py:full"
```

## Next

[Chapter 11: Testing Your Domain →](11-testing.md)
