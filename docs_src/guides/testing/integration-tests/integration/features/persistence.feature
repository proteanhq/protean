# tests/integration/features/persistence.feature
@integration
Feature: Persistence
    Verify that aggregates survive a round-trip through
    the real database.

    Background:
        Given the domain is initialized

    Scenario: Book survives persistence round-trip
        Given a book "The Great Gatsby" by "F. Scott Fitzgerald" at 12.99
        When the book is persisted and reloaded
        Then the reloaded book should have title "The Great Gatsby"
        And the reloaded book should have price 12.99

    Scenario: Updated aggregate is persisted correctly
        Given a book "Dune" by "Frank Herbert" at 15.99
        And the book is persisted
        When the book price is updated to 19.99
        And the book is persisted and reloaded
        Then the reloaded book should have price 19.99
