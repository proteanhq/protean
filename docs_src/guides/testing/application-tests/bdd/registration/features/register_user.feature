# tests/bdd/registration/features/register_user.feature
Feature: User Registration
    Users should be able to register through the Register command
    and receive a welcome notification.

    Background:
        Given the domain is initialized

    Scenario: Register a new user
        When a Register command is processed for "john@example.com"
        Then a user should exist with email "john@example.com"
        And the user status should be "INACTIVE"

    Scenario: Registration triggers a welcome notification
        When a Register command is processed for "jane@example.com"
        Then a welcome notification should have been sent to "jane@example.com"

    Scenario: Duplicate registration is rejected
        Given a user already exists with email "john@example.com"
        When a Register command is attempted for "john@example.com"
        Then the command should fail with error "already registered"
