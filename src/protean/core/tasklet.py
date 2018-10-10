"""Module defines the Tasklet class"""


class Tasklet:
    """Utility class to execute UseCases"""

    @classmethod
    def perform(cls, repo_factory, cls_schema, cls_usecase, cls_request_object,
                payload: dict):
        """
        This method bundles all essential artifacts and initiates usecase
        execution.
        :param repo_factory: The repository factory class for fetching the
        repository
        :param cls_schema: The schema class to be used for running the usecase
        :param cls_usecase: The usecase class that will be executed by
        the tasklet.
        :param cls_request_object: The request object to be used as input to the
        use case
        :param payload: The payload to be passed to the request object
        """

        # Get the Repository for the Current Schema
        repo = getattr(repo_factory, cls_schema.__name__)

        # Initialize the use case and request objects
        use_case = cls_usecase(repo)
        request_object = cls_request_object.\
            from_dict(cls_schema.opts.entity, payload)

        # Run the use case and return the results
        return use_case.execute(request_object)
