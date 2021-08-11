Composing a Domain
==================

A domain in Protean represents a ``Bounded Context`` of the application. Because it is aware of all domain elements,
the :class:`protean.Domain` in Protean acts as a ``Composition Root``, with which all modules are composed together.
It is responsible for creating and maintaining a graph of all the domain elements in the Bounded Context.

The Domain is the one-stop gateway to:

- Register domain elements
- Retrieve dynamically-constructed artifacts like repositories and models
- Access injected technology components at runtime

Initializing a Domain
---------------------

Constructing the object graph is a two-step procedure. First, you initialize a domain object at a reasonable starting
point of the application.

.. code-block:: python

    from protean import Domain
    domain = Domain(__name__)

Registering Elements to the Domain
----------------------------------

Next, the ``domain`` object is referenced by the rest of the application to register elements and participate
in application configuration.

.. code-block:: python

    from sample_app import domain

    @domain.aggregate
    class User:
        name = String()
        email = String(required=True)


Configuring a Domain
--------------------

You can pass a config file to the domain, like so:

.. code-block:: python

    domain.config.from_pyfile(config_path)

Refer to :doc:`config` to understand the different ways to configure the domain.

Activating a Domain
-------------------

A domain is activated by pushing up its context to the top of the domain stack.

.. code-block:: python

    context = domain.domain_context()
    context.push()

Subsequent calls to ``protean.globals.current_domain`` will return the currently active domain. Once the task has been
completed, it is recommended that the domain stack be reset to its original state by calling ``context.pop()``.

This is a convenient pattern to use in conjunction with most API frameworks. The domain's context is pushed up at the
beginning of a request and popped out once the request is processed.

When to compose
---------------

The composition should take place *as close to the application’s entry point as possible*. In simple console
applications, the ``Main`` method is a good entry point. But for most web applications that spin up their own runtime,
we depend on the callbacks or hooks of the framework to compose the object graph.

Accordingly, depending on the software stack you will ultimately use, you will decide when to compose the object graph.
For example, if you are using Flask as the API framework, you would compose the ``domain`` along with
the ``app`` object.

.. code-block:: python

    import logging.config
    import os

    from flask import Flask

    from sample_app import domain

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

Of note is the activation of the domain with the help of ``@app.before_request`` decorator above - this is
``Flask``-specific. Refer to :ref:`adapter-api` section to understand how to accomplish this for other frameworks.
