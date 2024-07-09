# Events

Most applications have a definite state - they reflect past user input and
interactions in their current state. It is advantageous to model these past
changes as a series of discrete events. Domain events happen to be those
activities that domain experts care about and represent what happened as-is.

In Protean, an `Event` is an immutable object that represents a significant
occurrence or change in the domain. Events are raised by aggregates to signal
that something noteworthy has happened, allowing other parts of the system to
react - and sync - to these changes in a decoupled manner.

## Defining Events

Event names should be descriptive and convey the specific change or occurrence
in the domain clearly, ensuring that the purpose of the event is immediately
understandable.  Events are named as past-tense verbs to clearly indicate
that an event has already occurred, such as `OrderPlaced` or `PaymentProcessed`.

You can define an event with the `Domain.event` decorator:

```python hl_lines="14-16 19-22 31-33 35-38"
{! docs_src/guides/domain-definition/events/001.py !}
```

Events are always connected to an Aggregate class, specified with the
`part_of` param in the decorator. An exception to this rule is when the
Event class has been marked _Abstract_.


## Event Structure

An event is made of three parts:

### Headers

#### `trace_id`

The `trace_id` is a unique identifier of UUID format, that connects all
processing originating from a request. Trace IDs provide a detailed view of
the request's journey through the system. It helps in understanding the
complete flow of a request, showing each service interaction, the time taken,
and where any delays occur.

### Metadata

An event's metadata provides additional context about the event.

#### `id`

The unique identifier of the event. The event ID is a structured string, of the
format **<domain>.<aggregate>.<version>.<aggregate-id>.<sequence_id>**.

#### `timestamp`

The timestamp of event generation.

#### `version`

The version of the event.

#### `sequence_id`

The sequence ID is the version of the aggregate when the event was generated,
along with the sequence number of the event within the update.

For example, if the aggregate was updated twice, the first update would have a
sequence ID of `1.1`, and the second update would have a sequence ID of `2.1`.
If the next update generated two events, then the sequence ID of the second
event would be `3.2`.

#### `payload_hash`

The hash of the event's payload.

## Payload

The payload is a dictionary of key-value pairs that convey the information
about the event.

The payload is made available as the data in the event. If
you want to extract just the payload, you can use the `payload` property
of the event.

```shell hl_lines="17 19-20"
In [1]: user = User(id="1", email="<EMAIL>", name="<NAME>")

In [2]: user.login()

In [3]: event = user._events[0]

In [4]: event
Out[4]: <UserLoggedIn: UserLoggedIn object ({'_metadata': {'id': '002.User.v1.1.0.1', 'timestamp': '2024-06-30 19:20:53.587542+00:00', 'version': 'v1', 'sequence_id': '0.1', 'payload_hash': 5473995227001335107}, 'user_id': '1'})>

In [5]: event.to_dict()
Out[5]: 
{'_metadata': {'id': '002.User.v1.1.0.1',
  'timestamp': '2024-06-30 19:20:53.587542+00:00',
  'version': 'v1',
  'sequence_id': '0.1',
  'payload_hash': 5473995227001335107},
 'user_id': '1'}

In [6]: event.payload
Out[6]: {'user_id': '1'}
```

## Versioning

Because events serve as API contracts of an aggregate with the rest of the
ecosystem, they are versioned to signal changes to contract.

By default, events have a version of **v1**.

You can specify a version with the `__version__` class attribute:

```python hl_lines="3"
@domain.event(part_of=User)
class UserActivated:
    __version__ = "v2"

    user_id = Identifier(required=True)
    activated_at = DateTime(required=True)
```

The configured version is reflected in `version` and `id` attributes of the
generated event:

```python hl_lines="34 50 52 66 68"
{! docs_src/guides/domain-definition/events/002.py !}
```

## Fact Events

A fact event encloses the entire state of the aggregate at that specific point
in time. It contains all of the attributes and values necessary to completely
describe the fact in the context of your business. You can think of a fact
event similarly to how you may think of a row in a database: a complete set of
data pertaining to the row at that point in time.

Fact events enable a pattern known as **Event-carried State Transfer**, which is
one of the best ways to asynchronously distribute immutable state to all
consumers who need it. With fact events, consumers do not have to build up the
state themselves from multiple delta event types, which can be risky and
error-prone, especially as data schemas evolve and change over time. Instead,
they rely on the owning service to compute and produce a fully detailed fact
event.

Fact events are generated automatically by the framework with the
`fact_events=True` option in the `domain.aggregate` decorator.

Read about generating fact events in the section on
[raising events](../domain-behavior/raising-events.md#fact-events).

## Immutability

Event objects are immutable - they cannot be changed once created. This is
important because events are meant to be used as a snapshot of the domain
state at a specific point in time.

```shell hl_lines="5 7-11"
In [1]: user = User(name='John Doe', email='john@doe.com', status='ACTIVE')

In [2]: renamed = UserRenamed(user_id=user.id, name="John Doe Jr.")

In [3]: renamed.name = "John Doe Sr."
...
IncorrectUsageError: {
    '_event': [
        'Event Objects are immutable and cannot be modified once created'
    ]
}
```
