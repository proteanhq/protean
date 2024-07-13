from protean import BaseEvent, BaseEventHandler, handle


class AllEventHandler(BaseEventHandler):
    @handle("$any")
    def universal_handler(self, event: BaseEventHandler) -> None:
        pass


class MultipleAnyEventHandler(BaseEventHandler):
    @handle("$any")
    def handler1(self, event: BaseEvent) -> None:
        pass

    @handle("$any")
    def handler2(self, event: BaseEvent) -> None:
        pass


def test_any_handler(test_domain):
    test_domain.register(AllEventHandler, stream_name="$all")
    test_domain.init(traverse=False)

    len(AllEventHandler._handlers) == 1
    assert AllEventHandler._handlers["$any"] == {AllEventHandler.universal_handler}


def test_that_there_can_be_only_one_any_handler_method_per_event_handler(test_domain):
    test_domain.register(MultipleAnyEventHandler, stream_name="$all")
    test_domain.init(traverse=False)

    assert len(MultipleAnyEventHandler._handlers["$any"]) == 1
    assert MultipleAnyEventHandler._handlers["$any"] == {
        MultipleAnyEventHandler.handler2
    }
