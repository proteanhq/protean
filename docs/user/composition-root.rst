.. _composition-root:

==================
Composing a Domain
==================

A domain is typically made up of many elements that work together to codify a concept. In accordance with DDD principles, these elements are not aware of the underlying technology layers.

Any external dependencies are made available dynamically during runtime. For example, an aggregate's repository is made available to the Application Service during runtime, using which it can save new aggregates or fetch existing aggregates from the underlying data store.

By doing this, elements push the responsibility of the creation of their dependencies up to their consumer. That consumer, in turn, may push the responsibility of the creation of its own dependencies higher up. But the creation of these dependencies cannot be delayed indefinitely. There must be a location in the application where we create our object graphs. This creation is better concentrated in a single area of the application called the **Composition Root**.

A Composition Root is (preferably) a unique location in an application where modules are composed together. It composes the object graph, which subsequently performs the actual work of the application.

**A Protean Domain represents such a composition root**. It is usually aligned 1-1 with bounded contexts in your application, and is responsible for creating and maintaining the graph of all elements in that Bounded Context.

.. note:: You may have more than one domain in your application depending on your application's bounded contexts.

Initializing a Domain
=====================

Constructing the object graph is a two-step procedure. First, you will need to initialize a domain object at a reasonable starting point of the application.

.. code-block:: python

    from protean.domain import Domain
    domain = Domain(__name__)

    domain.config.from_pyfile(config_path)

Refer to :ref:`configuration` to understand the different ways to configure the domain.

Registering Elements to the Domain
==================================

Next, the `domain` object is referenced by the rest of the application to register objects and participate in application configuration.

.. code-block:: python

    from sample_app import domain

    @domain.value_object
    class Balance:
        """A composite amount object, containing two parts:
            * currency code - a three letter unique currency code
            * amount - a float value
        """

        currency = String(max_length=3, required=True, choices=Currency)
        amount = Float(required=True)

When to compose
===============

The composition from many loosely coupled classes should take place *as close to the application’s entry point as possible*. In simple console applications, the `Main` method is a good entry point. But for most web applications that spin up their own runtime, we will have to depend on the callbacks or hooks the framework provides, to compose the object graph.

Accordingly, depending on the software stack you will ultimately use, you will decide when to compose the object graph. For example, if you are using Flask as the API framework, you would compose the `domain` along with the `app` object.

.. code-block:: python

    import logging.config
    import os

    from flask import Flask

    from vfc.domain import domain


    def create_app():
        app = Flask(__name__, static_folder=None)

        # Configure domain
        current_path = os.path.abspath(os.path.dirname(__file__))
        config_path = os.path.join(current_path, "./../config.py")
        domain.config.from_pyfile(config_path)

        logging.config.dictConfig(domain.config['LOGGING_CONFIG'])

        from api.views.registration import registration_api
        from api.views.user import user_api
        app.register_blueprint(registration_api)
        app.register_blueprint(user_api)

        @app.before_request
        def set_context():
            # Push up a Domain Context
            # This should be done within Flask App
            context = domain.domain_context()
            context.push()

        return app

Observe the activation of the domain with the help of ``@app.before_request`` decorator above. This is Flask-specific. Such activation will depend on your application's entry point, and will depend on the frameworks you use. Refer to :ref:`plugin-api` section to understand how to do this for your application framework.

A domain is activated by pushing up its context to the top of the domain stack. Subsequent calls to `protean.globals.current_domain` will return the currently active domain. Once the task has been completed, it is recommended that the domain stack is reset to its original state by calling `context.pop()`.
