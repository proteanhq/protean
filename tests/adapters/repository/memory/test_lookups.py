from datetime import datetime

from protean.adapters.repository.memory import Exact


class TestLookup:
    """This class holds tests for Lookup Class"""

    from protean.adapters.repository.memory import MemoryProvider
    from protean.port.dao import BaseLookup

    @MemoryProvider.register_lookup
    class SampleLookup(BaseLookup):
        """A simple implementation of lookup class"""

        lookup_name = "sample"

        def as_expression(self):
            return "%s %s %s" % (self.process_source(), "<<<>>>", self.process_target())

    def test_initialization_of_a_lookup_object(self):
        lookup = self.SampleLookup("src", "trg")
        assert lookup.as_expression() == "src <<<>>> trg"

    def test_registration_of_a_lookup_to_an_adapter(self):
        from protean.adapters.repository.memory import MemoryProvider

        assert MemoryProvider.get_lookups().get("sample") == self.SampleLookup

    def test_expression_constructed_for_datetime_fields(self):
        now = datetime.today()
        lookup = Exact("datetimefield", now)
        assert lookup is not None
        assert lookup.as_expression() == f'"datetimefield" == "{str(now)}"'

    def test_expression_constructed_for_date_fields(self):
        today = datetime.today().date()
        lookup = Exact("datefield", today)
        assert lookup is not None
        assert lookup.as_expression() == f'"datefield" == "{str(today)}"'
