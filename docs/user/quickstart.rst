.. _quickstart:

Quickstart (WIP)
================

This quick and brief guide will get you going on Protean with a basic setup. We will walk through the steps of implementing a simple use case with the Protean stack.

First, make sure that:

* Protean is :ref:`installed <install>`
* Protean is :ref:`up-to-date <changelog>`

Initialize a Domain Object
--------------------------

Begin by initializing a Domain Entity::

    class Account:
        id = field.Integer(identifier=True)
        firstname = field.String(required=True, max_length=50)
        lastname = field.String(max_length=50)
        age = field.Integer(default=5)
        email = field.String(required=True, max_length=50)

Construct a Use Case
--------------------

Let's allow a new user to register herserlf::

    from protean.core.usecase import CreateUseCase

    class Register(CreateUseCase):
    """ This class implements the usecase for registering a new user"""

    def process_request(self, request_object):
        """Register a new user"""
        data = request_object.data

        if Account.find_by(('email', data['email'])):
            return ResponseFailure.build_unprocessable_error({'email': 'Email already exists'})

        account = Account.create(request_object.data)

        return ResponseSuccessCreated(account)

Invoking the Use Case
---------------------

Call the use case with appropriate data, like so::

    from protean.core.tasklet import Tasklet

    payload = {'firstname': 'John', 'lastname': 'Doe', 'age': 25, 'email': 'johndoe@gmail.com'}
    Tasklet.perform(Account, Register, CreateRequestObject, payload=payload)

That's it! No, seriously!
You can now use this construct to invoke your domain driven application use case in any existing application or framework of your choice.

If you want to continue on the path and deploy on the Protean stack, continue reading.

Choose DB Adapter
-----------------

*Coming soon!*

Choose API Framework
--------------------

*Coming soon!*

Deploy
------

*Coming soon!*