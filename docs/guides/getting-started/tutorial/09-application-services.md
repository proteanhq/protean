# Chapter 9: Application Services — Coordinating Use Cases

So far we have command handlers for processing commands and event handlers
for reacting to events. But real applications also need a synchronous
coordination layer — something that handles a user's request end-to-end.
**Application services** fill this role.

## What Are Application Services?

An application service coordinates a specific **use case**. Each method
typically maps to one API endpoint or user action:

- `CatalogService.add_book(...)` → POST /books
- `CatalogService.get_book(id)` → GET /books/:id
- `CatalogService.search_books(...)` → GET /books?author=...

Application services are a thin orchestration layer. They do not contain
business logic — they delegate to aggregates, repositories, and domain
services.

## Building the CatalogService

```python
{! docs_src/guides/getting-started/tutorial/ch09.py [ln:47-80] !}
```

Key points:

- **`@domain.application_service(part_of=Book)`** registers the service
  with the Book aggregate.
- **`@use_case`** wraps each method in a Unit of Work — automatic
  transaction management, just like command handlers.
- Methods are plain Python — create aggregates, use repositories, return
  results.

## The `@use_case` Decorator

The `@use_case` decorator does two important things:

1. **Wraps the method in a Unit of Work** — if the method succeeds,
   changes are committed. If it raises an exception, everything rolls
   back.
2. **Provides a clear boundary** — each use case is a self-contained
   operation.

Without `@use_case`, you would need to manage transactions manually:

```python
# Without @use_case (manual)
def add_book(self, ...):
    with UnitOfWork() as uow:
        book = Book(...)
        repo.add(book)

# With @use_case (automatic)
@use_case
def add_book(self, ...):
    book = Book(...)
    repo.add(book)
```

## Application Services vs Command Handlers

Both coordinate state changes. When should you use which?

| Application Services | Command Handlers |
|---------------------|------------------|
| Synchronous, returns result immediately | Can run asynchronously via server |
| Called directly from API/UI layer | Dispatched via `domain.process()` |
| Good for request-response workflows | Good for fire-and-forget commands |
| Orchestrates multiple operations | Processes a single command |

They are not mutually exclusive. An application service might call
`domain.process()` internally, or a command handler might use shared
domain logic.

!!! tip "Choosing the Right Approach"
    For a typical web API:

    - Use **application services** for operations where the client
      needs an immediate response (e.g., creating a resource and returning
      its ID).
    - Use **command handlers** for operations that can be queued and
      processed in the background (e.g., bulk imports, long-running tasks).

## Using the Service

```python
{! docs_src/guides/getting-started/tutorial/ch09.py [ln:88-134] !}
```

Run it:

```shell
$ python bookshelf.py
=== Adding Books via CatalogService ===
Added: The Great Gatsby (ID: a3b2c1d0-...)
Added: Brave New World (ID: e5f6g7h8-...)
Added: 1984 (ID: i9j0k1l2-...)

=== Retrieving a Book ===
Found: The Great Gatsby by F. Scott Fitzgerald, $12.99

=== Searching Books ===
Total books: 3
  - The Great Gatsby by F. Scott Fitzgerald
  - Brave New World by Aldous Huxley
  - 1984 by George Orwell

All checks passed!
```

## Full Source

```python
{! docs_src/guides/getting-started/tutorial/ch09.py !}
```

## Summary

In this chapter you learned:

- **Application services** coordinate use cases, acting as the bridge
  between the API layer and the domain.
- **`@use_case`** wraps methods in a Unit of Work for automatic
  transaction management.
- Application services are a **thin orchestration layer** — they delegate
  to aggregates and repositories.
- Use application services for **synchronous request-response** flows,
  command handlers for **asynchronous** processing.

Sometimes business logic spans multiple aggregates — "place an order"
involves both the Order and Inventory. In the next chapter we will build
a **domain service** to handle this cross-aggregate coordination.

## Next

[Chapter 10: Domain Services →](10-domain-services.md)
