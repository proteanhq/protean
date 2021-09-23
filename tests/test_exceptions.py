import pickle

from protean.exceptions import ObjectNotFoundError


def test_pickling_of_exceptions():
    exc = ObjectNotFoundError({"_entity": "foo"})

    pickled_exc = pickle.dumps(exc)
    unpickled_exc = pickle.loads(pickled_exc)

    assert exc.messages == unpickled_exc.messages
