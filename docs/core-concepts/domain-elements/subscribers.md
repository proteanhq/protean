# Subscribers

Subscribers consume messages from external message brokers. They are the
entry point for data and signals that originate outside the bounded context —
events published by other services, webhook payloads relayed through a
message queue, or any external message that needs to trigger domain logic.

Where [event handlers](./event-handlers.md) react to events raised
*within* the domain, subscribers react to messages arriving *from outside*.
This distinction keeps internal event processing and external integration
cleanly separated.

## Facts

### Subscribers listen to external broker streams. { data-toc-label="External Messages" }

A subscriber is bound to a specific stream on a specific message broker. It
receives raw messages from that stream and is responsible for interpreting
them and translating them into domain operations.

### Subscribers are associated with a broker and a stream. { data-toc-label="Broker and Stream" }

Every subscriber declares which broker it connects to and which stream it
listens on. This explicit configuration makes the external dependency visible
and keeps the wiring declarative.

### Subscribers implement a call interface. { data-toc-label="Call Interface" }

Each subscriber defines a single processing method that receives the incoming
message payload. This keeps the contract simple — one subscriber, one stream,
one processing entry point.

### Subscribers act as an anti-corruption layer. { data-toc-label="Anti-corruption" }

External systems use their own schemas, naming conventions, and data formats.
The subscriber is the place to translate those external representations into
the domain's own language before triggering [commands](./commands.md) or
domain operations. This prevents external models from leaking into the core
domain.

### Subscribers can trigger domain operations. { data-toc-label="Trigger Domain Logic" }

After parsing and translating an external message, a subscriber typically
initiates a domain operation — submitting a command, invoking an
[application service](./application-services.md), or directly interacting
with an [aggregate](./aggregates.md) through its
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
