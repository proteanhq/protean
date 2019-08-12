.. _subscriber:

===========
Subscribers
===========

Subscribers live on the other side of event publishing. They are domain elements that subscribe to specific domain events and are notified by the domain on event bubble-up.

Protean provides a concrete message broker infrastructure as well as guaranteed transfer mechanisms. So Subscribers are agnostic to how the messages make their way to them. They can tap into Protean's infrastructure by specifying the domain event to attach to as part of their definition.

Subscribers implement their functionality in the ``notify`` function, which receives the domain event as an argument. Typically, they end up triggering a call to an Application Service method that accesses the rest of the infrastructure to execute the behavior. Asynchronous processes, long-drawn and expensive transactions and communication across bounded contexts are good candidates to be executed through domain events.

Usage
=====

A Subscriber can be defined and registered with the help of ``@domain.subscriber`` decorator:

.. testsetup:: *

    import os
    from protean.domain import Domain

    domain = Domain('Test')

    ctx = domain.domain_context()
    ctx.push()

.. doctest::

    @domain.subscriber(domain_event='CommentAdded')
    class SendNewCommentEmail:
        """Send an email alerting the author about a new comment"""

        def notify(self, domain_event):
            email_body = self.construct_email_body_from_domain_event(domain_event)
            current_domain.service_for(Email).send(domain_event.author, email_body)

        def construct_email_body_from_domain_event(self, domain_event):
            ...
            return body
