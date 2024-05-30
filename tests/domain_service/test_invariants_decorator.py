from protean import BaseAggregate, BaseDomainService, invariant


class Aggregate1(BaseAggregate):
    pass


class Aggregate2(BaseAggregate):
    pass


class test_handler(BaseDomainService):
    class Meta:
        part_of = [Aggregate1, Aggregate2]

    @invariant.pre
    def some_invariant_1(self):
        pass

    @invariant.post
    def some_invariant_2(self):
        pass

    def __call__(self):
        pass


def test_that_domain_service_has_recorded_invariants(test_domain):
    test_domain.register(Aggregate1)
    test_domain.register(Aggregate2)
    test_domain.register(test_handler)
    test_domain.init(traverse=False)

    assert len(test_handler._invariants) == 2

    # Methods are presented in ascending order (alphabetical order) of member names.
    assert "some_invariant_1" in test_handler._invariants["pre"]
    assert "some_invariant_2" in test_handler._invariants["post"]
