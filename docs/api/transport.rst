.. _api-transport:

Transfer Objects
----------------

RequestObjectFactory
^^^^^^^^^^^^^^^^^^^^

.. _api-request-object-factory-construct:

``construct()``
~~~~~~~~~~~~~~~

.. automethod:: protean.core.transport.RequestObjectFactory.construct

.. _api-request-object:

RequestObject
^^^^^^^^^^^^^

.. autoclass:: protean.core.transport.RequestObject

.. _api-request-object-from-dict:

``from_dict()``
~~~~~~~~~~~~~~~

.. automethod:: protean.core.transport.RequestObject.from_dict

.. _api-invalid-request-object:

InvalidRequestObject
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: protean.core.transport.InvalidRequestObject

.. _api-response-object:

Response Objects
^^^^^^^^^^^^^^^^

.. _api-response-success:

ResponseSuccess
~~~~~~~~~~~~~~~

.. autoclass:: protean.core.transport.response.ResponseSuccess

.. _api-response-failure:

ResponseFailure
~~~~~~~~~~~~~~~

.. autoclass:: protean.core.transport.response.ResponseFailure

.. _api-response-failure-build-response:

.. automethod:: protean.core.transport.response.ResponseFailure.build_response

.. _api-response-failure-build-from-invalid-request:

.. automethod:: protean.core.transport.response.ResponseFailure.build_from_invalid_request

.. _api-response-failure-build-not-found:

.. automethod:: protean.core.transport.response.ResponseFailure.build_not_found

.. _api-response-failure-build-system-error:

.. automethod:: protean.core.transport.response.ResponseFailure.build_system_error

.. _api-response-failure-build-parameters-error:

.. automethod:: protean.core.transport.response.ResponseFailure.build_parameters_error

.. _api-response-failure-build-unprocessable-error:

.. automethod:: protean.core.transport.response.ResponseFailure.build_unprocessable_error
