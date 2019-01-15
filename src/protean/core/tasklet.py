"""Module defines the Tasklet class"""
from protean.core.exceptions import UsecaseExecutionError
from protean.core.transport import ResponseFailure


class Tasklet:
    """Utility class to execute UseCases"""

    @classmethod
    def perform(cls, entity_cls, usecase_cls, request_object_cls,
                payload: dict, raise_error=False):
        """
        This method bundles all essential artifacts and initiates usecase
        execution.
        :param entity_cls: The entity class to be used for running the usecase
        :param usecase_cls: The usecase class that will be executed by
        the tasklet.
        :param request_object_cls: The request object to be used as input to the
        use case
        :type request_object_cls: protean.core.Request
        :param payload: The payload to be passed to the request object
        :type payload: dict
        :param raise_error: Raise error when a failure response is generated
        :type raise_error: bool
        """

        # Initialize the use case and request objects
        use_case = usecase_cls()
        request_object = request_object_cls.from_dict(entity_cls, payload)

        # Run the use case and return the response
        resp = use_case.execute(request_object)

        # If raise error is set then check the response and raise error
        if raise_error and isinstance(resp, ResponseFailure):
            raise UsecaseExecutionError(
                (resp.code, resp.value),
                orig_exc=getattr(resp, 'exc', None),
                orig_trace=getattr(resp, 'trace', None)
            )
        return resp
