.. _quickstart:

==========
Quickstart
==========

A Minimal Application
=====================

A minimal Protean application looks something like this:

.. code-block:: python

    from protean.domain import Domain
    domain = Domain(__name__)


    @domain.aggregate
    class User:
        from protean.core.field.basic import String
        name = String(required=True)

    if __name__ == '__main__':
        user = User(name='John')
        user_repo = domain.repository_for(User)
        user_repo.add(user)

        persisted_user = user_repo.get(user.id)
        print("Persisted User: ", persisted_user.to_dict())

.. note::
    It is recommended that you use a virtual env to install and use a specific python version. We love |pyenv|, and you can automate the process of creating a virtual env with |pyenv-virtualenv|. Simply run:

    .. code-block:: console

        >>> pyenv virtualenv -p python3.7 3.7.4 quickstart-dev

Assuming you have :ref:`installed <install>` protean already, in this code snippet:

* First, we imported the ``Domain`` class. An instance of this class will be our domain's :ref:`composition-root`.
* Next, we create an instance of this class. The first argument is the name of the domain. If you are using a single domain (as in this example), you should use __name__ so that Protean knows where to look for domain elements. For more information have a look at the :ref:`api-domain` documentation.
* We then declare a ``User`` :ref:`aggregate` in the domain with the ``@aggregate`` decorator. The decorator also registers the element with the domain.
* A simple ``String`` attribute called `name` is declared as part of the ``User`` aggregate.
* We then initialize a new `user` object with the name attribute set to 'John'
* The repository associated with `User` aggregate is fetched from the domain. In this case, a repository class is constructed by the domain itself and provided to us.
* The `user` object is then saved to the repository. By default, Protean provides an in-memory dictionary implementation of database, and that is used in our case.
* To verify that everything has gone according to plan, we fetch the `user` object again with the help of the repository and print its contents.

Just save it as `user.py` or something similar. Make sure to not call your application `domain.py` because this would conflict with Protean itself.

To run the application, simply call the script from a console configured with the right Python version:

.. code-block:: console

    >>> python user.py

    Persisted User:  {'name': 'John', 'id': '7617a94c-1f48-4f93-ab15-f42956622d47'}

You should see something similar printed in your console.

Writing your first Test Case
============================

Configuration
-------------

Installing Pytest
-----------------

First Test Case
---------------

Configuring and persisting to a Database
========================================

Configuration
-------------

Repositiory
-----------

Persistence
-----------

Connecting an API and exposing a RESTful route
==============================================

Configuration
-------------

Installing Flask
----------------

First Route
-----------

Logging
=======


.. |pyenv| raw:: html

    <a href="https://github.com/pyenv/pyenv" target="_blank">pyenv</a>

.. |pyenv-virtualenv| raw:: html

    <a href="https://github.com/pyenv/pyenv-virtualenv" target="_blank">pyenv-virtualenv</a>
