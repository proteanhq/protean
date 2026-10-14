# --8<-- [start:feature]
# tests/integration/features/order_flow.feature
@integration
Feature: End-to-End Order Flow
    Verify the complete order lifecycle from book creation
    through order placement, including event-driven side effects.

    Background:
        Given the domain is initialized

    Scenario: Full order lifecycle
        Given a book "Dune" is added to the catalog at 15.99
        And the book has 10 copies in stock
        And a customer "Alice" exists
        When "Alice" places an order for 2 copies of "Dune"
        Then the order status should be "CONFIRMED"
        And "Dune" should have 8 copies in stock
        And the catalog projection should show 2 copies sold for "Dune"

    Scenario: Order updates customer history across aggregates
        Given a book "1984" is added to the catalog at 11.99
        And the book has 5 copies in stock
        And a customer "Bob" exists
        When "Bob" places an order for 2 copies of "1984"
        Then "Bob" should have 1 order in their history
# --8<-- [end:feature]
