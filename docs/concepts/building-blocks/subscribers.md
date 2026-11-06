# Subscribers

Subscribers consume messages from external message brokers. Subscribers are the
entry point for data and signals from outside the bounded context. These
include events published by other services, webhook payloads relayed through a
message queue, and any external message that needs to trigger domain logic.

Where [event handlers](./event-handlers.md) react to events raised *within* the
domain, subscribers react to messages arriving *from outside*. Protean gives
each kind of message its own element, so internal event processing and external
integration stay separate.

## Facts

### Subscribers listen to external broker streams. { data-toc-label="External Messages" }

A subscriber is bound to a specific stream on a specific message broker. It
receives raw messages from that stream. It interprets each message and
translates it into domain operations.

### Subscribers are associated with a broker and a stream. { data-toc-label="Broker and Stream" }

Every subscriber declares the broker it connects to. It also declares the
stream it listens on. With this explicit configuration, you can see the
external dependency in the subscriber definition, and you keep the wiring
declarative.

### Subscribers implement a call interface. { data-toc-label="Call Interface" }

Each subscriber defines a single processing method that receives the incoming
message payload. With a single processing method, the contract stays simple:
one subscriber, one stream, one processing entry point.

### Subscribers act as an anti-corruption layer. { data-toc-label="Anti-corruption" }

External systems use their own schemas, naming conventions, and data formats.
The subscriber translates those external representations into the domain's own
language before it triggers [commands](./commands.md) or domain operations.
Because the subscriber does this translation, code in the core domain does not
depend on external models.

### Subscribers can trigger domain operations. { data-toc-label="Trigger Domain Logic" }

After parsing and translating an external message, a subscriber typically
starts a domain operation: it submits a command, invokes an [application
service](./application-services.md), or loads and changes an
[aggregate](./aggregates.md) directly through its
[repository](./repositories.md).

### Subscribers support error handling. { data-toc-label="Error Handling" }

Subscribers can define error-handling logic for when message processing fails.
This allows the system to log failures, route messages to a dead-letter queue,
or attempt retries without crashing the message consumer.

### Subscribers differ from event handlers. { data-toc-label="Not Event Handlers" }

Event handlers subscribe to domain event streams managed by the framework's
event store. Subscribers subscribe to external broker streams managed by
infrastructure outside the domain. The two elements serve different
integration boundaries and should not be confused.

---

## Next steps

For practical details on defining and using subscribers in Protean, see the guide:

- [Subscribers](../../guides/consume-state/subscribers.md): Defining subscribers, configuration, processing modes, and error handling.

For design guidance:

- [Consuming Events from Other Domains](../../patterns/consuming-events-from-other-domains.md): Patterns for integrating with external bounded contexts.
