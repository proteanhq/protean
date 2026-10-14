# tests/bdd/registration/features/activate_user.feature
Feature: User Activation
    Registered users can be activated through the application service.

    Background:
        Given the domain is initialized

    Scenario: Activate a registered user
        Given a registered user "john@example.com"
        When the user is activated
        Then the user status should be "ACTIVE"

    Scenario: Cannot activate a non-existent user
        When activation is attempted for a non-existent user
        Then the operation should fail with "does not exist"
