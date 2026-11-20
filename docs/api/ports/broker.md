# BrokerPort

Message broker interface. Every broker adapter (Inline, Redis Stream,
Redis PubSub, or your own) subclasses `BaseBroker` and `BrokerPort`, in that
order. `BrokerPort` lists the operations Protean calls on every broker.
`BaseBroker` stores the adapter's name, domain and configuration. A broker
that declares a capability with its own Port subclasses that Port in place of
`BrokerPort`. Each of these Ports extends `BrokerPort`:

- `BLOCKING_READ`: `BlockingReadPort`, the blocking reads.
- `DEAD_LETTER_QUEUE`: `DeadLetterQueuePort`, the dead letter queue operations.
- `STREAM_PARTITIONING`: `PartitioningPort`, the partition-per-key operations.
- `STREAM_RETENTION`: `StreamRetentionPort`, stream trimming.

`domain.brokers[name]` returns a `Broker` service that wraps the adapter.
Application code calls the service, not the adapter.

See [Broker Adapters](../../reference/adapters/broker/index.md) for
concrete adapter configuration, and
[Custom Brokers](../../reference/adapters/broker/custom-brokers.md) for
writing an adapter.

::: protean.port.broker.BrokerPort
    options:
      show_root_heading: false

## BlockingReadPort

::: protean.port.broker.BlockingReadPort
    options:
      show_root_heading: false

## DeadLetterQueuePort

::: protean.port.broker.DeadLetterQueuePort
    options:
      show_root_heading: false

## PartitioningPort

::: protean.port.broker.PartitioningPort
    options:
      show_root_heading: false

## StreamRetentionPort

::: protean.port.broker.StreamRetentionPort
    options:
      show_root_heading: false

## Records

::: protean.port.broker.BrokerMessage
    options:
      show_root_heading: true
      heading_level: 3

::: protean.port.broker.BrokerHealth
    options:
      show_root_heading: true
      heading_level: 3

::: protean.port.broker.DLQEntry
    options:
      show_root_heading: true
      heading_level: 3

::: protean.port.broker.ConsumerGroupInfo
    options:
      show_root_heading: true
      heading_level: 3

::: protean.port.broker.ConsumerInfo
    options:
      show_root_heading: true
      heading_level: 3

## BaseBroker

::: protean.port.broker.BaseBroker
    options:
      show_root_heading: false

## Broker service

::: protean.infra.broker.Broker
    options:
      show_root_heading: false
