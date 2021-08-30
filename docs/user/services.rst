Exposing the domain
===================

A domain rarely stands alone by itself. You eventually have to expose the domain to other services or at least a user interface, for it to be of any use. Your application has to interact with the database, load pre-existing data, coordinate transactions, and dispatch events, all while relying on the domain model to protect invariants and maintain data sanctity. Application Services are the primary vehicles that help you connect your domain to the external world.

Application Services are the direct clients of the domain model. They are responsible for task coordination of use case flows, ideally one service method per flow. All aspects related to infrastructure, like security (user authentication, permissions, and authorization), persistence (data fetch and data save, transactions), and messaging (publishing and receiving messages), occur in the Application layer.

Routing requests to Application Services
----------------------------------------

You can define an Application service with `@domain.application_service` decorator:

.. code-block:: python

    @domain.application_service
    class UserRegistration:

        def register(first_name, last_name, password, email):
            ...

Typically, an application service fetches the data from the database, loads the relevant parts of the domain model, and coordinates an action.

.. code-block:: python

    @domain.application_service
    class OrderServices:
        @classmethod
        def change_delivery_address(order_id, address1, address2, address3, city, country, zipcode):
            order_repo = current_domain.repository_for(order_id)
            order = order_repo.get(order_id)

            order.change_address(address1, address2, address3, city, country, zipcode)

            order_repo.add(order)
