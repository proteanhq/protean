Quickstart
==========

Eager to get started? This page gives a good introduction to Protean. Follow :doc:`installation` to set up a project and install Protean first.

In this quickstart, we will write a simple Protean application with SQLITE as the database and Flask as the API framework.

A Simple Domain
---------------

A simple Protean domain looks something like this:

.. code-block:: python

    from protean import Domain

    domain = Domain(__name__)

Here's what we did:

1. First we imported the :class:`protean.Domain` class. An instance of this class will be our domain root to which all elements are attached.
2. Next, we create an instance of this class. The optional argument is the name of the domain's module or package. ``__name__`` is a convenient shortcut for this that is appropriate for most cases, so it is the default if no name is specified explicitly.

Define an Aggregate
-------------------

Aggregates are the basic building blocks of the domain. Use the :meth:`protean.Domain.aggregate` decorator to bind an Aggregate to the domain.

.. code-block:: python

    from protean.core.field import String

    @domain.aggregate
    class User:
        name = String(max_length=50)
        email = String(max_length=255, unique=True)

Define an Application Service
-----------------------------

Application services expose the domain to the external world. You can create an Application Service with the help of :meth:`protean.Domain.application_service` decorator.

.. code-block:: python

    @domain.application_service
    class SignupService:
        @classmethod
        def signup(cls, name, email):
            user = User(name=name, email=email)
            domain.repository_for(User).add(user)

            return user

Configure a database
--------------------

By default, a Protean domain is configured with an :class:`protean.adapters.repository.MemoryProvider` that manages a dictionary database in memory. This database is handy when you get started with your domain, especially for testing purposes. You can also specify an alternate implementation by overriding the database config. Let's do that and specify an SQLITE database.

Note that Protean uses SQLAlchemy to access the SQLITE database internally.

.. code-block:: python

    domain.config["DATABASES"]["default"] = {
        "PROVIDER": "protean.adapters.repository.sqlalchemy.SAProvider",
        "DATABASE": "SQLITE",
        "DATABASE_URI": "sqlite:///quickstart.db",
    }

A database file ``quickstart.db`` will be created in the location you will be running your application from.

Configure Flask
---------------

Let's next expose the domain to the external world via APIs with |flask|. We accomplish this by activating <TO-LINK> the domain in a function that runs before every request.

We also register a function to run before Flask processes the very first request, in which we set up the database with a table whose structure is auto-generated from the Aggregate definition.

.. code-block:: python

    from flask import Flask

    app = Flask(__name__)

    @app.before_first_request
    def set_context():
        with domain.domain_context():
            for provider in domain.providers_list():
                for _, aggregate in domain.registry.aggregates.items():
                    domain.get_dao(aggregate.cls)

                provider._metadata.create_all()

    @app.before_request
    def set_context():
        context = domain.domain_context()
        context.push()

.. |flask| raw:: html

    <a href="https://flask.palletsprojects.com/" target="_blank">Flask</a>

Define a route
--------------

We are now ready to define API routes for the domain. Let's create a route that helps us create new users as well as returns a list of all existing users.

.. code-block:: python

    @app.route("/users", methods=["GET", "POST"])
    def users():
        if request.method == "POST":
            user = SignupService.signup(request.form['name'], request.form['email'])
            return json.dumps(user.to_dict()), 201
        else:
            users = current_domain.repository_for(User).all()
            return json.dumps([user.to_dict() for user in users]), 200

Start the Flask server
----------------------

To run the Flask application, use the ``flask`` command or ``python -m flask``. The snippet below assumes that your code is saved in a file named ``quickstart.py``. If it is not, adjust the command accordingly.

.. code-block:: shell

    $ export FLASK_APP=quickstart
    $ flask run

If all is well, you should see a success message at the console along with the URL to access the Flask server.

Access the domain over APIs
---------------------------

You can access the APIs once the server is running. We can use |httpie| to fire requests from the console. Let's first fire a ``POST`` request to create a user.

.. code-block:: shell

    http -f POST http://localhost:5000/users name=John email=john.doe@example.com

You should see a success message with the user record that was just created.

.. code-block:: shell

    HTTP/1.0 201 CREATED
    Content-Length: 95
    Content-Type: text/html; charset=utf-8
    Date: Mon, 09 Aug 2021 16:19:31 GMT
    Server: Werkzeug/1.0.1 Python/3.9.4

    {
        "email": "john.doe@example.com",
        "id": "41de0f44-9dd0-4ac9-98e3-5e2eca498511",
        "name": "John"
    }

We can now fire a ``GET`` request to retrieve all users from the database.

.. code-block:: shell

    http http://127.0.0.1:5000/users

    HTTP/1.0 200 OK
    Content-Length: 97
    Content-Type: text/html; charset=utf-8
    Date: Mon, 09 Aug 2021 16:19:36 GMT
    Server: Werkzeug/1.0.1 Python/3.9.4

    [
        {
            "email": "john.doe@example.com",
            "id": "41de0f44-9dd0-4ac9-98e3-5e2eca498511",
            "name": "John"
        }
    ]

.. |httpie| raw:: html

    <a href="https://httpie.io/" target="_blank">HTTPie</a>

--------------------

That's it! You have now created a simple Protean domain with SQLITE and Flask and accessed it over the web.
