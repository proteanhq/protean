class TestLookup:
    """This class holds tests for Lookup Class"""

    from protean.core.repository.lookup import BaseLookup
    from protean.impl.repository.dict_repo import DictProvider

    @DictProvider.register_lookup
    class SampleLookup(BaseLookup):
        """A simple implementation of lookup class"""
        lookup_name = "sample"

        def as_expression(self):
            return '%s %s %s' % (self.process_source(),
                                 '<<<>>>',
                                 self.process_target())

    def test_initialization_of_a_lookup_object(self):
        lookup = self.SampleLookup("src", "trg")
        assert lookup.as_expression() == "src <<<>>> trg"

    def test_registration_of_a_lookup_to_an_adapter(self):
        from protean.impl.repository.dict_repo import DictProvider
        assert DictProvider.get_lookups().get('sample') == self.SampleLookup
