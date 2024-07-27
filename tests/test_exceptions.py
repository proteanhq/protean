import pickle

import pytest

from protean.exceptions import (
    ObjectNotFoundError,
    ProteanException,
    ProteanExceptionWithMessage,
)


def test_pickling_of_exceptions():
    exc = ObjectNotFoundError("foo")

    pickled_exc = pickle.dumps(exc)
    unpickled_exc = pickle.loads(pickled_exc)

    assert exc.args[0] == unpickled_exc.args[0]


class TestProteanException:
    @pytest.fixture
    def exception_instance(self):
        return ProteanException("An error occurred")

    def test_exception_initialization(self, exception_instance):
        assert exception_instance.args[0] == "An error occurred"
        assert exception_instance.extra_info is None

    def test_exception_with_extra_info(self):
        exception_instance = ProteanException(
            "An error occurred", extra_info="Extra info"
        )
        assert exception_instance.extra_info == "Extra info"

    def test_exception_no_args(self):
        exception_instance = ProteanException()
        assert exception_instance.args == ()

    def test_exception_multiple_args(self):
        exception_instance = ProteanException(
            "Error 1", "Error 2", extra_info="Extra info"
        )
        assert exception_instance.args == ("Error 1", "Error 2")
        assert exception_instance.extra_info == "Extra info"


class TestProteanExceptionWithMessage:
    def test_exception_initialization(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        assert exception_instance.messages == {"error": "An error occurred"}
        assert exception_instance.traceback is None

    def test_exception_str(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        assert str(exception_instance) == "{'error': 'An error occurred'}"

    def test_exception_reduce(self):
        messages = {"error": "An error occurred"}
        exception_instance = ProteanExceptionWithMessage(messages)

        reduced = exception_instance.__reduce__()
        assert reduced[0] is ProteanExceptionWithMessage
        assert reduced[1] == ({"error": "An error occurred"},)

    def test_exception_with_traceback(self):
        messages = {"error": "An error occurred"}
        traceback = "Traceback info"
        exception_instance = ProteanExceptionWithMessage(messages, traceback=traceback)

        assert exception_instance.traceback == traceback

    def test_exception_with_additional_kwargs(self):
        messages = {"error": "An error occurred"}
        extra_info = "Extra info"
        exception_instance = ProteanExceptionWithMessage(
            messages, extra_info=extra_info
        )

        assert exception_instance.messages == messages
        assert exception_instance.traceback is None
        assert exception_instance.extra_info == extra_info
