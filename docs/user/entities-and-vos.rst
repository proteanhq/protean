Aggregate Elements
==================

Aggregates, by definition, cluster multiple domain elements together to represent a concept. They are usually composed of two kinds of elements: those with unique identities (``Entities``) and those without (``Value Objects``).

Entities
--------

Entities represent unique objects in the domain model. They are very similar to Aggregates except that they don't manage other objects. In fact, Aggregates are actually entities that have taken on the additional responsibility of managing the lifecycle of one or more related entities.

Entities are identified by their unique identities that remain the same throughout its life - they are not defined by their attributes or values. For example, a passenger in the airline domain is an Entity. The passenger's identity remains the same across multiple seat bookings, even if her profile information (name, address, etc.) changes over time.

It is also important to note that an Entity in one domain may not be an Entity in another. For example, a seat is an Entity if airlines distinguish each seat uniquely on every flight. If passengers are not allotted specific seats, then a seat can be considered a ``ValueObject``, as one seat can be exchanged with another. We will explain Value Objects in detail further in this section.

You can define and register an Entity by annotating it with the ``@domain.entity`` decorator:

.. code-block:: python

    from protean.domain import Domain
    from protean.core.field.basic import Date, String

    publishing = Domain(__name__)

    @publishing.aggregate
    class Post:
        name = String(max_length=50)
        created_on = Date()

    @publishing.entity(aggregate_cls=Post)
    class Comment:
        content = String(max_length=500)

An Entity's Aggregate can also be specified as an attribute of the ``Meta`` class:

.. code-block:: python

    @publishing.entity
    class Comment:
        content = String(max_length=500)

        class Meta:
            aggregate_cls = Post

Properties
``````````

Entities share all traits of Aggregates like id-based equality, inheritance, and abstraction, except that they cannot enclose other entities. They usually map 1-1 with structures in the persistent store (tables or documents) and only enclose basic fields or Value Objects.

.. // FIXME Unimplemented Feature

Trying to specify other entity fields throws a ``IncorrectUsageError``.

Relationships
-------------

Protean provides multiple options with which Aggregates can weave object graphs with enclosed Entities. We will explore the different relationships between an Aggregate and its enclosed Entities with the example domain below.

.. code-block:: python

    @publishing.aggregate
    class Post:
        title = String(max_length=50)
        created_on = Date(default=datetime.utcnow)

        stats = HasOne('Statistic')
        comments = HasMany('Comment')


    @publishing.entity(aggregate_cls=Post)
    class Statistic:
        likes = Integer()
        dislikes = Integer()
        post = Reference(Post)


    @publishing.entity(aggregate_cls=Post)
    class Comment:
        content = String(max_length=500)
        post = Reference(Post)
        added_at = DateTime()

HasOne
``````

A `HasOne` field establishes a ``has-one`` relation with the remote entity. In the example above, ``Post`` has exactly one ``Statistic`` record associated with it.

.. code-block:: python

    >>> post = Post(title='Foo')
    >>> post.stats = Statistic(likes=10, dislikes=1)
    >>> current_domain.repository_for(Post).add(post)

HasMany
```````

A `HasMany` field establishes a ``one-to-many`` relation with the remote entity. In the example above, ``Post`` can be associated with one or more comments.

Field values can be added with field-specific utility methods:

.. code-block:: python

    >>> post = Post(title='Foo')
    >>> comment1 = Comment(content='bar')
    >>> comment2 = Comment(content='baz')
    >>> post.add_comments([comment1, comment2])
    >>> current_domain.repository_for(Post).add(post)

    >>> post.remove_comments(comment2)
    >>> current_domain.repository_for(Post).add(post)

Reference
`````````

A ``Reference`` field establishes the opposite relationship with the parent at the data level. Entities that are connected by HasMany and HasOne relationships can reference their owning object.

.. code-block:: python

    >>> reloaded_post = current_domain.repository_for(Post).get(post)
    >>> assert reloaded_post.comments[0].post == reloaded_post
    True

Value Objects
-------------

A Value Object is a domain element that represents a distinct domain concept, with attributes, behavior and validations built into them. They tend to act primarily as data containers, usually enclosing attributes of primitive types.

Consider the simple example of an Email Address. A User's `Email` can be treated as a simple "String." If we do so, validations that check for the value correctness (an email address) are either specified as part of the User lifecycle methods (in `save`, `before_save`, etc.) or as independent business logic present in the services layer.

But an `Email`  is more than just another string in the system (say like First Name or Last Name). It has well-defined, explicit rules associated with it, like:

* The presence of an ``@`` symbol
* A string with acceptable characters (like ``.`` or ``_``) before the ``@`` symbol
* A valid domain URL right after the ``@`` symbol
* The domain URL to be among the list of acceptable domains, if defined
* A total length of less 255 characters
* and so on.

So it makes better sense to make `Email` a Value Object, with a simple string representation to the outer world, but having a distinct `local_part` (the part of the email address before `@`) and `domain_part` (the domain part of the address). Any value assignment has to satisfy the domain rules listed above.

Equality
````````

Two value objects are considered to be equal if their values are equal.

.. code-block:: python

    @domain.value_object
    class Balance:
        currency = String(max_length=3, required=True)
        amount = Float(required=True)

.. code-block:: python

    >>> bal1 = Balance(currency='USD', amount=100.0)
    >>> bal2 = Balance(currency='USD', amount=100.0)
    >>> bal3 = Balance(currency='CAD', amount=100.0)

    >>> bal1 == bal2
    True
    >>> bal1 == bal3
    False

Identity
````````

Value Objects do not have unique identities.

.. // FIXME Unimplemented Feature

Unlike Aggregates and Entities, Value Objects do not have any inbuilt concept of unique identities. Trying to mark a Value Object field as ``unique = True`` or ``identifier = True`` will throw a :class:`~protean.exceptions.IncorrectUsageError` exception.

.. code-block:: python

    >>> bal1.meta_.declared_fields
    {'currency': <protean.core.field.basic.String object at 0x10c7488b0>,
    'amount': <protean.core.field.basic.Float object at 0x10c748790>}

    >>> bal1.meta_.id_field
    Traceback (most recent call last):
    File "<input>", line 1, in <module>
        bal1.meta_.id_field
    AttributeError: 'ContainerMeta' object has no attribute 'id_field'

Immutability
````````````

.. // FIXME Unimplemented Feature

A Value Object cannot be altered once initialized. Trying to do so will throw a ``TypeError``.

.. code-block:: python

    >>> bal1 = Balance(currency='USD', amount=100.0)

    >>> bal1.currency = 'CAD'
    Traceback (most recent call last):
    File "<input>", line 1, in <module>
        bal1.currency = 'CAD'
    TypeError: value object is immutable

Embedding Value Objects
-----------------------

Value Objects can be embedded into Aggregates and Entities as part of their attributes.

.. code-block:: python

    @domain.value_object
    class Money:
        currency = String(max_length=3)
        amount = Float()

    @domain.aggregate
    class Account:
        name = String(max_length=50)
        balance = ValueObject(Money)

.. code-block:: python

    >>> Account.meta_.attributes
    {'name': <protean.core.field.basic.String object at 0x106bc6dc0>,
    'balance_currency': <protean.core.field.embedded._ShadowField object at 0x106bc61f0>,
    'balance_amount': <protean.core.field.embedded._ShadowField object at 0x106bc6c40>,
    'id': <protean.core.field.basic.Auto object at 0x106836850>}

As visible in the output above, the names of Value Object attributes are generated dynamically. The names are a combination of the attribute name in the enclosed container and the names defined in the Value Object, separated by underscores. So `currency` and `amount` are available as `balance_currency` and `balance_amount` in the ``Account`` Aggregate.

You can override these automatically generated names with the `referenced_as` option in the Value Object:

.. code-block:: python

    @domain.value_object
    class Money:
        currency = String(max_length=3)
        amount = Float(referenced_as="amt")

The supplied attribute name is used as-is in enclosed containers:

.. code-block:: python

    >>> Account.meta_.attributes
    {'name': <protean.core.field.basic.String object at 0x107381700>,
    'balance_currency': <protean.core.field.embedded._ShadowField object at 0x1073806d0>,
    'amt': <protean.core.field.embedded._ShadowField object at 0x107380610>,
    'id': <protean.core.field.basic.Auto object at 0x1073804f0>}

Examples
--------

Email
`````

.. code-block:: python

    @domain.value_object
    class Email:
        """An email address value object, with two identified parts:
            * local_part
            * domain_part
        """

        # This is the external facing data attribute
        address = String(max_length=254, required=True)

        def __init__(self, *template, local_part=None, domain_part=None, **kwargs):
            """ `local_part` and `domain_part` are internal attributes that capture
            and preserve the validity of an Email Address
            """

            super(Email, self).__init__(*template, **kwargs)

            self.local_part = local_part
            self.domain_part = domain_part

            if self.local_part and self.domain_part:
                self.address = '@'.join([self.local_part, self.domain_part])
            else:
                raise ValidationError("Email address is invalid")

        @classmethod
        def from_address(cls, address):
            """ Construct an Email VO from an email address.

            email = Email.from_address('john.doe@gmail.com')

            """
            if not cls.validate(address):
                raise ValueError('Email address is invalid')

            local_part, _, domain_part = address.partition('@')

            return cls(local_part=local_part, domain_part=domain_part)

        @classmethod
        def from_parts(cls, local_part, domain_part):
            """ Construct an Email VO from parts of an email address.

            email = Email.from_parths(local_part='john.doe', domain_part='@gmail.com')

            """
            return cls(local_part=local_part, domain_part=domain_part)

        @classmethod
        def validate(cls, address):
            """ Business rules of Email address """
            if type(address) is not str:
                return False
            if '@' not in address:
                return False
            if len(address) > 255:
                return False

            return True

Address
```````

.. code-block:: python

    @domain.value_object
    class Address:
        address1 = String(max_length=255, required=True)
        address2 = String(max_length=255)
        address3 = String(max_length=255)
        city = String(max_length=25, required=True)
        state = String(max_length=25, required=True)
        country = String(max_length=2, required=True, choices=CountryEnum)
        zip = String(max_length=6, required=True)

        def validate_with_canada_post(self):
            return CanadaPostService.verify(self.to_dict())

Account Balance
```````````````

An Account's Balance consists of two parts: a Currency (string) and an Amount (float). It may have restrictions like positive balance and supported currencies.

.. code-block:: python

    class Currency(Enum):
        """ Set of choices for the status"""
        USD = 'USD'
        INR = 'INR'
        CAD = 'CAD'


    @domain.value_object
    class Balance:
        """A composite amount object, containing two parts:
            * currency code - a three letter unique currency code
            * amount - a float value
        """

        currency = String(max_length=3, required=True, choices=Currency)
        amount = Float(required=True, min_value=0.0)

Temperature
```````````

A valid Temperature contains two parts, a scale (Celsius or Fahrenheit) and a temperature integer value. The application may want to place restrictions on a range of acceptable values, and specify that only positive temperature values are allowed.

.. // FIXME Unimplemented Feature - choices can be a `list`

.. code-block:: python

    @domain.value_object
    class Temperature:
        scale = String(max_length=1, required=True, choices=['C', 'F'])
        degrees = Integer(required=True, min_value=-70, max_value=500)


Account
```````

The ``Account`` entity below encloses an ``Email`` Value Object and is part of a ``Profile`` Aggregate.

.. code-block:: python

    @domain.entity(aggregate_cls='Profile')
    class Account:
        email = ValueObject(Email, required=True)
        password = String()

    @domain.aggregate
    class Profile:
        first_name = String(max_length=50)
        last_name = String(max_length=50)
        account = HasOne(Account)
