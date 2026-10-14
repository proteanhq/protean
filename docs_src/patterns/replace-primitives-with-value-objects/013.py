from protean import Domain, invariant
from protean.exceptions import ValidationError
from protean.fields import Float, String, ValueObject

domain = Domain(name="NestedValueObjects")


# --8<-- [start:nested]
@domain.value_object
class GeoLocation:
    latitude: Float(required=True)
    longitude: Float(required=True)

    @invariant.post
    def coordinates_must_be_valid(self):
        if not (-90 <= self.latitude <= 90):
            raise ValidationError({"latitude": ["Latitude must be between -90 and 90"]})
        if not (-180 <= self.longitude <= 180):
            raise ValidationError(
                {"longitude": ["Longitude must be between -180 and 180"]}
            )


@domain.value_object
class Address:
    street: String(required=True)
    city: String(required=True)
    state: String(required=True)
    postal_code: String(required=True)
    country: String(max_length=2, required=True)
    location = ValueObject(GeoLocation)  # Optional geo coordinates


# --8<-- [end:nested]

domain.init(traverse=False)
