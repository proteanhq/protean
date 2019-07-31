.. _quickstart:

==========
Quickstart
==========

A Minimal Application
=====================

A minimal Protean domain looks something like this:

.. code-block:: python

    from protean.domain import Domain
    domain = Domain(__name__)

    @domain.aggregate
    class User:
        from protean.core.field.basic import String
        name = String(required=True)

In this code snippet:

* First, we imported the ``Domain`` class. An instance of this class will be our domain's :ref:`composition-root`.
* Next, we created an instance of this class. The first argument is the name of the domain. If you are using a single domain (as in this example), you should use __name__ so that Protean knows where to look for domain elements. For more information have a look at the :ref:`api-domain` documentation.
* We then declare a ``User`` aggregate in the domain with the ``@aggregate`` decorator, that registers the element with the domain.
* A simple ``String`` attribute called name is declared as part of the ``User`` aggregate.


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
