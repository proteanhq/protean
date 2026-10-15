# --8<-- [start:feature]
# tests/bdd/ordering/features/place_order.feature
@ordering @smoke
Feature: Place Order
    Customers can place orders that trigger inventory updates
    and customer history tracking.

    Background:
        Given the domain is initialized

    @happy_path
    Scenario: Placing an order updates inventory
        Given a book "Dune" with 10 copies in stock
        And a customer "Alice"
        When "Alice" places an order for 2 copies of "Dune"
        Then the order should be confirmed
        And "Dune" should have 8 copies in stock

    Scenario: Placing an order records customer history
        Given a book "1984" with 5 copies in stock
        And a customer "Bob"
        When "Bob" places an order for 2 copies of "1984"
        Then "Bob" should have 1 order in their history

    @validation
    Scenario: Cannot order more than available stock
        Given a book "Rare Book" with 2 copies in stock
        And a customer "Charlie"
        When "Charlie" tries to order 10 copies of "Rare Book"
        Then the order should be rejected with "Insufficient stock"
# --8<-- [end:feature]

# --8<-- [start:outline]
    Scenario Outline: Order total is calculated correctly
        Given a customer "Alice"
        And "Alice" adds <quantity> copies of a book priced at <price>
        When "Alice" places the order
        Then the order total should be <total>

        Examples:
            | quantity | price | total  |
            | 1        | 10.00 | 10.00  |
            | 3        | 20.00 | 60.00  |
            | 2        | 15.50 | 31.00  |
# --8<-- [end:outline]
