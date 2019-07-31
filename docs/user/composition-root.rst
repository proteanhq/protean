.. _composition-root:

================
Composition Root
================

A typical domain is made up of many elements that work together to illustrate the domain concept.

Most of these elements will have internal elements, but will also need external dependencies injected into them, typically Constructors or Factory methods. By doing this, they push the responsibility of the creation of their dependencies up to their consumer. That consumer may again push the responsibility of the creation of its dependencies higher up.

But the creation of these classes cannot be delayed indefinitely. There must be a location in the application where we create our object graphs. This creation is better concentrated in a single area of the application. This place is called the Composition Root.

A Composition Root is a (preferably) unique location in an application where modules are composed together.

The Composition Root composes the object graph, which subsequently performs the actual work of the application. Such composing from many loosely coupled classes should take place *as close to the application’s entry point as possible*. In simple console applications, the `Main` method is a good entry point. But for most web applications that spin up their own runtime, we will have to depend on the callbacks or hooks the framework provides, to compose the object graph.

Using the `domain` Composition Root
===================================

Once the `domain` object has been defined and loaded, it can be referenced from the rest of the application to register objects and participate in application configuration.

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
