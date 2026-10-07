from protean import Domain
from protean.fields import DateTime, Float

domain = Domain(name="Scheduling")


# --8<-- [start:value_object]
@domain.value_object
class Duration:
    start: DateTime(required=True)
    end: DateTime(required=True)
    total_seconds: Float()

    def defaults(self):
        if self.total_seconds is None and self.start and self.end:
            self.total_seconds = (self.end - self.start).total_seconds()


# --8<-- [end:value_object]
