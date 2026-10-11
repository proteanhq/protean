"""A repository that stores an aggregate and then raises, for the change-state tests."""


class AddFails(Exception):
    """The failure a repository raises after it has stored the order."""


class RepositoryThatFailsAfterAdd:
    """Stores the aggregate, then raises, as a flush that fails part-way would.

    Without a Unit of Work around the call, the real ``add()`` commits at once,
    so the change survives the error. Inside one, the error rolls it back.
    """

    def __init__(self, repository, fail_on=None):
        self._repository = repository
        self._fail_on = fail_on

    def add(self, item):
        self._repository.add(item)
        if self._fail_on is None or item is self._fail_on:
            raise AddFails()
        return item

    def __getattr__(self, name):
        return getattr(self._repository, name)
