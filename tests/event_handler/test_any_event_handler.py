from protean import BaseEventHandler, handle


class AllEventHandler(BaseEventHandler):
    @handle("$any")
    def universal_handler(self, event: BaseEventHandler) -> None:
        pass

    class Meta:
        stream_name = "$all"


class MultipleAnyEventHandler(BaseEventHandler):
    @handle("$any")
    def handler1(self, event: BaseEventHandler) -> None:
        pass

    @handle("$any")
    def handler2(self, event: BaseEventHandler) -> None:
        pass

    class Meta:
        stream_name = "$all"


def test_any_handler(test_domain):
    test_domain.register(AllEventHandler)

    len(AllEventHandler._handlers) == 1
    assert AllEventHandler._handlers["$any"] == {AllEventHandler.universal_handler}


def test_that_there_can_be_only_one_any_handler_method_per_event_handler(test_domain):
    test_domain.register(MultipleAnyEventHandler)

    assert len(MultipleAnyEventHandler._handlers["$any"]) == 1
    assert MultipleAnyEventHandler._handlers["$any"] == {
        MultipleAnyEventHandler.handler2
    }
