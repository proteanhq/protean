================
Transfer Objects
================

Transfer Objects (or DTOs as they are popularly known) are objects that carry data between processes. They encapsulate data, and send it from one subsystem of an application to another, reducing the amount of data that needs to be sent across the wire in distributed applications while also ensuring the necessary data is passed.

Protean has built in support for constructing request and response objects for passing data to and from servics. These objects closely mimic HTTP/REST interactions and bring the familiar status codes, actions and behavior to your application.

Entities or Value Objects can serve as Transfer Objects, but it is generally not recommended to use them as they have specific domain connotations. Transfer Objects, on the other hand, are tied to a specific service; their lifetime is limited to the service's process time. They also have built-in support for tracking return codes (which are nothing but HTTP Status Codes) and errors.

Request Objects
---------------

A Request Transfer Object is constructed typically from input data to an API and passed forward to the Service object. You can construct unique Request Object classes tied to each service with the help of the RequestObjectFactory, like so:

.. code-block:: python

    from protean.core.entity import Entity
    from protean.core.transport import RequestObjectFactory

    LoginRequestObject = RequestObjectFactory.construct(
        'LoginRequestObject',
        [('email', str, {'required': True}),
         ('password', str, {'required': True}),
         ('remember_me', bool, {'default': False}])

The :ref:`api-request-object-factory-construct` method accepts two arguments: the ``name`` of the RequestObject Class and an iterable containing its field definitions.

Each field definition is a tuple of three elements:
* ``name``: The name of the field
* ``type``: The type of value stored in the field
* ``options``: An optional `dict` that allows you to control two aspects:
* ``required``: If ``required`` is True, the field needs to be present in the data supplied while initializing the request object. If its absent, the request object will be deemed invalid.
* ``default``: If ``default`` is specified, its value will be set to the field if the field is not supplied during initialization.

Each element can either have just the ``name``, or ``(name, type)``, or the full-fledged ``(name, type, Field)``. If just ``name`` is supplied, ``typing.Any`` is used as the field's type.

``required is ``False`` by default, so ``{required: False, default: 'John'}`` and ``{default: 'John'}`` evaluate to the same field definition. Note that ``default`` is a concrete value of the correct type, and cannot be a callable.

In the example above, `email` and `password` are attributes of the `LoginRequestObject` class. ``email`` and ``password`` have both been marked as required, so the request object will be treated as invalid if they are not supplied. ``remember_me`` is not required, and will be defaulted to ``False`` if not supplied.

An actual request object can then be created with the class:

.. code-block:: python

    request_object = UserShowRequestObject.from_dict(
        {'email': 'johndoe@gmail.com', 'passwrod': 'secret'})

If you need to implement complex Request Objects, with custom validations and transformations, you can directly subclass from :ref:`api-request-object` and override ``from_dict`` class method.

.. code-block:: python

    class ShowRequestObject(ValidRequestObject):
    """
    This class encapsulates the Request Object for retrieving a resource
    """

    def __init__(self, entity_cls, identifier=None):
        """Initialize Request Object with ID"""
        self.entity_cls = entity_cls
        self.identifier = identifier

    @classmethod
    def from_dict(cls, entity_cls, adict):
        """Initialize a ShowRequestObject object from a dictionary."""
        invalid_req = InvalidRequestObject()

        identifier = None
        if 'identifier' in adict:
            identifier = adict['identifier']
        else:
            invalid_req.add_error('identifier', 'is required')

        if invalid_req.has_errors:
            return invalid_req

        return cls(entity_cls, identifier)

If the request object is not valid, it's ``is_valid`` flag will evaluate to false, and an object of :ref:`api-invalid-request-object` will be returned. You can inspect ``errors`` attribute on the object to get parameterized error messages:

.. code-block:: python

    >>> request_object = UserShowRequestObject.from_dict(
            {'email': 'johndoe@gmail.com'})
    >>> request_object.is_valid
    False
    >>> type(request_object)
    InvalidRequestObject

Response Objects
----------------

A Response Transfer Object is constructed and returned as output from a Service object. Response objects contain success codes and/or values given by the service if they are successful, and errors if the service call failed.

Consider a simply retrieval case of an entity that is already persisted:

.. code-block:: python

    from protean.core.usecase import ShowRequestObject
    from protean.core.usecase import ShowUseCase

    # Build the request object and run the usecase
    request_obj = ShowRequestObject.from_dict({'entity_cls': Dog, 'identifier': 1})
    use_case = ShowUseCase()
    response = use_case.execute(request_obj)

The ``response`` object contains all necessary information returned from the service call, and ``is_successful`` flag helps you check if the processing was successful .

.. code-block:: python

    >>> response.is_successful
    True

ResponseSuccess
^^^^^^^^^^^^^^^

On successfully processing a request, a ``ResponseSuccess`` object is returned. A ``ResponseSuccess`` object usually carries three attributes:

* ``code``: A HTTP 2xx success status code
* ``value``: The value returned by the service - Can be ``None`` for code 204 (Success Response with no content)
* ``message``: An optional message sent by the service

.. code-block:: python

    >>> type(response)
    <class 'protean.core.transport.response.ResponseSuccess'>
    >>> response.is_successful
    True
    >>> response.code
    <Status.SUCCESS: 200>
    >>> type(response.value)
    <class 'Dog'>
    >>> response.value.to_dict()
    {'age': 5, 'id': 1, 'name': 'Johnny', 'owner': 'John'}

ResponseFailure
^^^^^^^^^^^^^^^

If the service call failed, a ``ResponseFailure`` object is returned, containing:

* ``code``: A HTTP 4xx/5xx failure status code
* ``errors``: A list of key-value errors, with key being the `parameter` or `argument` that triggered the error and `value` being a helpful message

.. code-block:: python

    >>> type(response)
    <class 'protean.core.transport.response.ResponseFailure'>
    >>> response.is_successful
    False
    >>> response.code
    <Status.NOT_FOUND: 404>
    >>> response.errors
    [{'identifier': 'Object with this ID does not exist.'}]

``ResponseFailure`` class provides many helper methods to construct HTTP style errors. Refer to :ref:`api-response-failure` for full documentation.
