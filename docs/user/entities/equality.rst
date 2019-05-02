.. _entity-equality:

Equality
--------

Equality in Entities are based on their unique identities. Two entities are considered equal if and only if they are of the same type, and have the same identity.

Let's see some examples of equality in action:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core import field

    class Dog(Entity):
        """This is a dummy Dog Entity class"""
        name = field.String(required=True, max_length=50)
        age = field.Integer(default=5)
        owner = field.String(required=True, max_length=15)

.. code-block:: python

    >>> dog1 = Dog.create(name='Slobber 1', age=6, owner='Jason')
    <tests.support.dog.Dog at ...>
    >>> dog2 = Dog.create(name='Slobber 2', age=6, owner='Jason')
    <tests.support.dog.Dog at ...>
    >>> dog1 != dog2
    True

And an example of what seems too obvious:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core import field

    class Human(Entity):
        """This is a dummy Human Entity class"""
        first_name = field.String(required=True, unique=True, max_length=50)
        last_name = field.String(required=True, unique=True, max_length=50)
        email = field.String(required=True, unique=True, max_length=50)

.. code-block:: python

    >>> human = Human(id=dog.id, ...)
    <tests.support.human.Human at ...>
    >>> dog1 != human  # Not equal, even though they have the same identity
    True

This even applies to objects of sub-classes:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core import field

    class Puppy(Dog):
        """This is a dummy Human Entity class"""
        pass

.. code-block:: python

    >>> puppy = Puppy(id=dog.id, ...)
    <tests.support.dog.Puppy at ...>
    >>> dog1 != puppy  # Not equal, even though they have the same identity
    True
