from protean import BaseDomainService


class DummyDomainService(BaseDomainService):
    def do_complex_process(self):
        print("Performing complex process...")
