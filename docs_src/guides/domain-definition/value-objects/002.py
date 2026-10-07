from protean import Domain
from protean.fields import Float, String, ValueObject

domain = Domain(name="Stores")


# --8<-- [start:value_objects]
@domain.value_object
class GeoLocation:
    latitude: Float(required=True)
    longitude: Float(required=True)


@domain.value_object
class Address:
    street: String(max_length=200)
    city: String(max_length=100)
    zip_code: String(max_length=10)
    location = ValueObject(GeoLocation)


# --8<-- [end:value_objects]


# --8<-- [start:nested]
@domain.aggregate
class Store:
    name: String(max_length=100)
    address = ValueObject(Address)


domain.init(traverse=False)

with domain.domain_context():
    store = Store(
        name="Downtown",
        address=Address(
            street="123 Main St",
            city="Springfield",
            zip_code="62701",
            location=GeoLocation(latitude=39.78, longitude=-89.65),
        ),
    )
    assert store.address.location.latitude == 39.78
# --8<-- [end:nested]

# --8<-- [start:flattened]
with domain.domain_context():
    store = Store(
        name="Downtown",
        address_street="123 Main St",
        address_city="Springfield",
        address_zip_code="62701",
        address_location=GeoLocation(latitude=39.78, longitude=-89.65),
    )
    assert store.address.city == "Springfield"
# --8<-- [end:flattened]
