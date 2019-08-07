.. _value-object:

=============
Value Objects
=============

Value objects are "Conceptual Whole" data elements. They act as containers of one or more attributes, with behavior and validations built into them. The set of attributes tend to be primitive, and represent a domain concept when considered together.

Consider the simple example of an Email Address. A User's `Email` can be treated as a simple "String." If we do so, validations that check for the value correctness (an email address) are either specified as part of the User lifecycle methods (in `save`, `before_save`, etc.) or as independent business logic present in the services layer.

But an `Email`  is more than just another string in the system (say like First Name or Last Name). It has well-defined, explicit rules associated with it, like:

* The presence of an ``@`` symbol
* A string with acceptable characters (like `.`, `_`) before the ``@`` symbol
* A valid domain URL right after the ``@`` symbol
* The domain URL to be among the list of acceptable domains, if defined
* A total length of less 255 characters
* and so on.

So it makes better sense to make `Email` a Value Object, with a simple string representation to the outer world, but having a distinct `local_part` (the part of the email address before `@`) and `domain_part` (the domain part of the address). Any value assignment has to satisfy the domain rules listed above.

Qualities
=========

How can one identify what elements in a domain are candidates for becoming Value Objects? Here are some characteristics:

* It measures, quantifies, or describes a thing in the domain (should be a domain concept)
* It is used in multiple contexts and parts of the application
* It has one or more invariant rules (a.k.a validations)
* It is a cluster of two or more attributes that act as an integral unit, making a conceptual whole
* It is entirely replaceable when the measurement or description changes
* It makes sense to compare it with other objects only using value equality

Properties
==========

Value Objects have well-defined generic behavior, supported by the Protean subsystem.

**1. Value Objects do not have an identity.**

Value Objects do not carry a unique identifier (a.k.a an `id` a.k.a a primary key) with them.

Let's again consider the example of a Customer entity in our domain, with Address and Email Value Objects.

.. code-block:: python

    class Customer(BaseAggregate):
        first_name = String(max_length=255, required=True)
        last_name = String(max_length=255)
        email = ValueObjectField(Email)
        address = ValueObjectField(Address)

For this example, let us assume that a separate table holds Address values in the database. You would care about having access to the customer's address via the Customer object, viz. customer.address.city, or even customer.zipcode. Would we care what the `id` of the Address row is in the table? Probably not.

So from a business or domain point of view, Value objects (like an address) tend not to have a concept of identity. They don't have unique identifiers that could be used to get hold of them individually. This rule holds, irrespective of whether you store the address attributes in line with other fields in the parent data, or you persist them separately on their own.

Also, Value Objects don't have to be tracked separately for changes during their lifetime. Their instances are created and maintained on the fly (imagine that they are only on the RAM), and eventually destroyed in memory. Aggregates or entities that own the value objects take care of their persistence, as needed.

**2. Two Value Objects are considered to be equal if their values are equal.**

You wouldn't care whether two integer objects in memory are different if they both have a value of 5. They are replaceable; you don't care which "instance" is being used at any point in time. A similar thought process applies to the example of Balance value object below. You wouldn't care about differentiating between two objects if they both represent $100:

.. code-block:: python

    balance = Balance(currency=Currency.USD.value, amount=100.0)

For Python comparisons, we could use the underlying data dictionary to compare the values of two objects. Protean generically accomplishes this with the help of a `to_dict` method:

.. code-block:: python

    if type(other) is not type(self):
            return False

        return self.to_dict() == other.to_dict()

**3. Value Objects are Immutable.**

A Value Object cannot be altered once initialized.

To understand why this is necessary, let us refer to the first part of this thread where we talked about what attributes make excellent candidates as Value Objects.

If you have a currency value object of 50 USD, would you be able to update the amount value to 100? How about if you are trying to do this with an actual 50 USD note in hand?

Let's go one level deeper, and consider an arbitrary number, say 6. Why is 6 immutable? 6 is immutable because 6's identity is determined by what it represents, namely the state of having six of something. You can't change what the number 6 represents.

Immutability is a fundamental concept of Value Objects: State determines Value. Contrast this with an Entity, which depends on a unique identifier because it's state could change over it's lifetime. A `Customer`, for example, can change their address and still be the same Customer.

Consider object sharing as another example to understand why Value Objects need to be immutable. Say we have one Address Value Object is shared between two Customers. You cannot change the shared address because it may affect both customers. For an object to be shared safely, it must be immutable: It can only change with full replacement.

There is another considerable benefit that results from this property: Value Objects need to be validated only on initialization!

You can forget about all those callbacks or `before_save` methods we would need to write to ensure the data is valid before being persisted. When we want to alter a value object, we simply create a new instance (either by passing all attributes again or by using the earlier value object as a template and specifying only the changed attributes). Moreover, this validation would only happen during initialization time.

Generally, validation of Value Objects should not take place in their constructor. Constructors, as a rule, should not include logic, but should simply assign values. Validation, if required, should be part of a factory method. In languages like Java and C# that support access modifiers, it is a typical pattern to make Value Objects' constructors private and provide one or more public static methods for creating the Value Object. This achieves separation of concerns since constructing an instance from a set of values is a separate concern from ensuring the values are valid. The same concept ensures that a Value Object can be easily reconstituted from the database using the constructor, but building a new instance of Value Object through the factory method runs all validations.

Immutability is the primary reason for reducing code complexity, if Value Objects are used as attributes of Aggregates/Entities. Their management and data behavior becomes pretty simple and predictable.

**4. Value Objects depict Domain Concepts**

We earlier discussed Value Objects being Conceptually Whole. They illustrate and explain a domain concept. It may have one or more attributes as part of itself, but to the parent object, it is merely a property with behavior.

Consider a simple `FullName` Value Object below:

.. code-block:: python

    from enum import Enum

    from protean.core.value_object import BaseValueObject
    from protean.core import field


    class Titles(Enum):
        MR = 'Mr.'
        MRS = 'Mrs.'
        MS = 'Ms.'

    class FullName(BaseValueObject):
        first_name = field.String(max_length=50)
        middle_name = field.String(max_length=50)
        last_name = field.String(max_length=50)
        initials = field.String(max_length=3)
        title = field.String(max_length=5, choices=Titles)

By implementing a Value Object, instead of creating a bunch of attributes as simple strings in an Entity, you now have a good representative of a `FullName` Domain Concept, and you can tune its behavior and invariants to your heart's content.

**5. Value Objects exhibit Side-Effect-Free Behavior**

All methods of a Value Object must be Side-Effect-Free Functions because they must not violate its immutability quality.

This property is a fundamental requirement of immutability, but not always apparent. It pays to consider it carefully because of its immense benefits in writing robust and bug-free code.

.. note::
    Though often used interchangeably, there are subtle differences between the concepts of a method and a function.

    A function is an operation of an object that produces output but without modifying its state. Since no modification occurs when executing a specific action, that operation is said to be side-effect free. Methods, in contrast, tend to be associated with an object and operate on the data, usually modifying it.

    Developers also have a more topical way of distinguishing between functions and methods. In languages like Python, functions can be invoked by their names, while methods are typically associated with an object. So if you are calling a method on a call, you are dealing with a technique, while a function is what you would write without associating it with a class.

Consider a simplistic example of a side-effect free function for the FullName Value Object:

.. code-block:: python

    def in_second_order(self):
        return ', '.join(
            [self.last_name,
            ' '.join([self.first_name, self.middle_name])])

The function returns a fully formatted second-order name, without affecting the internal state, making it side-effect free.

We should strive to construct as many, if not all, methods to be side-effect free. If a function needs to change the Value Object in some way, you are better off making it a factory method (or a @classmethod in the class) and returning a fully-formed Value Object instance with the changed attributes.

Is Everything a Value Object?
-----------------------------

By now you may have begun to think that everything in your code looks like a Value Object. That’s better than treating data attributes as plain primitive types, or even separately stored Entities with unique IDs.

You can exercise caution when there are straightforward attributes that don’t need any special treatment. You may have Boolean attributes or numeric values that are self-contained, requiring no additional functional support, and are related to no other aspects in the same Entity. On their own, these simple attributes are Meaningful Whole objects.

Still, it is ok to occasionally make the “mistake” of unnecessarily wrapping a single attribute in a Value type with no unique functionality. If you find that you’ve overdone it a bit, you can always refactor a little.

Usage
=====

A Value Object (VO) can be defined in two ways:

1. As a class inheriting from ``BaseValueObject``

.. code-block:: python

    class Balance(BaseValueObject):
        """A composite amount object, containing two parts:
            * currency code - a three letter unique currency code
            * amount - a float value
        """

        currency = String(max_length=3, required=True, choices=Currency)
        amount = Float(required=True)

You will then have to register the Value Object with the domain:

.. code-block:: python

    domain.register(Balance)

2. As a class annotated with ``@domain.value_object``

.. code-block:: python

    @domain.value_object
    class Balance:
        """A composite amount object, containing two parts:
            * currency code - a three letter unique currency code
            * amount - a float value
        """

        currency = String(max_length=3, required=True, choices=Currency)
        amount = Float(required=True)

In this case, registration is automatic and does not require manual registration of the domain element.

You can assign a VO's value by instantiating an object of the class:

.. code-block:: python

    email = Email.from_address('john.doe@gmail.com')
    email = Email.from_parts('john.doe', 'gmail.com')

Updating Value Objects is as simple as replacing the existing value with a new instance:

    johns_email = Email.from_address('john.do@gmail.com')
    # Typo in email... Let's fix that.
    johns_email = Email.from_address('john.doe@gmail.com')

This aspect is again a consequence of the VO's Immutability, and can be used effectively to create side-effect free methods. Since a Value Object, once constructed, cannot be changed, you build a new one and replace the existing object.

This property becomes essential when you are evaluating or looking for Value Objects in your codebase. If you are leaning toward the creation of an Entity because the attributes of the object must change, challenge your assumptions to check if it’s the correct model. Would object replacement work instead?

Examples
========

Email
-----

.. code-block:: python

    class Email(BaseValueObject):
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
-------

An excellent example of a conceptual whole is how we capture an `Address` in the system. There are many elements associated with an address, like the type of Address (Home/Work), three separate lines to capture the full address (Address 1, Address 2 and Address 3), City, State, Country, and Zip.

We can treat these elements as individual data attributes of a user/account entity, but is it correct to do so? What if the city or country was left blank? What if an external source verifies the zip code?

A better way would be to create a Value Object called `Address`, and capture all data elements as part of it, enforced by rules and even external API validation (Canada and US, for example, have well-published Address APIs that can be used to crosscheck the validity of an address.)

.. code-block:: python

    class Address(BaseValueObject):
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
---------------

An Account's Balance consists of two parts: a Currency (string) and an Amount (float). It may have restrictions like positive balance and supported currencies.

.. code-block:: python

    class Currency(Enum):
        """ Set of choices for the status"""
        USD = 'USD'
        INR = 'INR'
        CAD = 'CAD'


    class Balance(BaseValueObject):
        """A composite amount object, containing two parts:
            * currency code - a three letter unique currency code
            * amount - a float value
        """

        currency = String(max_length=3, required=True, choices=Currency)
        amount = Float(required=True)

Temperature
-----------

A valid Temperature contains two parts, a scale (Celsius or Fahrenheit) and a temperature integer value. The application may want to place restrictions on a range of acceptable values, and specify that only positive temperature values are allowed.

.. code-block:: python

    class Temperature(BaseValueObject):
        scale = String(max_length=1, required=True, choices=['C', 'F'])
        degrees = Integer(required=True, min_value=-70, max_value=500)
