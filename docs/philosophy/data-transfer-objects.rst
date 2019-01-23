.. _philosophy-data-transfer-objects:

Transferring Data across Layers
===============================

Since the core of Protean deals with pure domain related problems, without worrying about what goes on in the external world, data from outside is represented/assumed in the form of simple Python objects.

Mirroring the HTTP world, Protean comes with inbuilt support for representing Request and Response Objects.

.. autoclass:: protean.core.transport.ValidRequestObject
   :members:

.. autoclass:: protean.core.transport.InvalidRequestObject
   :members:

.. autoclass:: protean.core.transport.ResponseSuccess
   :members:

.. autoclass:: protean.core.transport.ResponseSuccessWithNoContent
   :members:

.. autoclass:: protean.core.transport.ResponseSuccessCreated
   :members:

.. autoclass:: protean.core.transport.ResponseFailure
   :members:
