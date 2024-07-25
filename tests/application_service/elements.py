from protean.core.application_service import BaseApplicationService


class DummyApplicationService(BaseApplicationService):
    def do_application_process(self):
        print("Performing application process...")
