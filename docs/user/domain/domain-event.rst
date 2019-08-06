.. _domain-events:

=============
Domain Events
=============



The Domain Model should not be exposed to the messaging infrastructure. An event should be submitted to the domain, and it should be left to the domain to transport it to subscribers.
