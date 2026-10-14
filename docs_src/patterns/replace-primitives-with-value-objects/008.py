from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Auto, Date, String, ValueObject

domain = Domain(name="DateRangeValueObject")


# --8<-- [start:date_range]
@domain.value_object
class DateRange:
    start_date: Date(required=True)
    end_date: Date(required=True)

    @invariant.post
    def end_must_be_after_start(self):
        if self.end_date <= self.start_date:
            raise ValidationError({"end_date": ["End date must be after start date"]})

    def contains(self, date) -> bool:
        return self.start_date <= date <= self.end_date

    def overlaps(self, other: "DateRange") -> bool:
        return self.start_date <= other.end_date and other.start_date <= self.end_date

    def duration_days(self) -> int:
        return (self.end_date - self.start_date).days


@domain.aggregate
class Campaign:
    campaign_id: Auto(identifier=True)
    name: String(required=True)
    active_period = ValueObject(DateRange, required=True)

    def is_active_on(self, date) -> bool:
        return self.active_period.contains(date)


# --8<-- [end:date_range]

domain.init(traverse=False)
