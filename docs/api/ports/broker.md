# BrokerPort

Message broker interface. Every broker adapter (Inline, Redis Stream,
Redis PubSub, or your own) subclasses `BaseBroker` and `BrokerPort`, in that
order. `BrokerPort` lists the operations Protean calls on every broker.
`BaseBroker` holds the optional ones: blocking reads, dead letters,
partitions and trimming.

`domain.brokers[name]` returns a `Broker` service that wraps the adapter.
Application code calls the service, not the adapter.

See [Broker Adapters](../../reference/adapters/broker/index.md) for
concrete adapter configuration, and
[Custom Brokers](../../reference/adapters/broker/custom-brokers.md) for
writing an adapter.

::: protean.port.broker.BrokerPort
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
