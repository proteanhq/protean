# `protean observatory`

The `observatory` command runs the Protean Observatory — a dedicated
observability dashboard for real-time monitoring of the Protean event pipeline.
It runs on its own port (default 9000), separate from your application API
server.

The Observatory provides:

- An embedded HTML dashboard at the root URL
- Server-Sent Events (SSE) for real-time trace streaming
- REST API endpoints for health, outbox status, stream info, and throughput stats
- A Prometheus-compatible metrics endpoint

## Usage

```shell
protean observatory [OPTIONS]
```

## Options

| Option      | Description                          | Default                |
|-------------|--------------------------------------|------------------------|
| `--domain`  | Domain module path(s) to monitor. Repeatable for multi-domain setups. | *(required)* |
| `--host`    | Host to bind the server to.          | `0.0.0.0`             |
| `--port`    | Port to bind the server to.          | `9000`                 |
| `--title`   | Title shown in the dashboard.        | `Protean Observatory`  |
| `--debug`   | Enable debug logging.                | `False`                |
| `--help`    | Shows the help message and exits.    |                        |

## Starting the Observatory

### Single domain

To launch the observatory for a single domain:

```shell
protean observatory --domain auth
```

This will start the dashboard on `http://0.0.0.0:9000`. Read
[Domain Discovery](../project/discovery.md) for options to specify the domain.

### Multiple domains

To monitor several domains at once (e.g. in a multi-domain application):

```shell
protean observatory --domain identity --domain catalogue
```

Each `--domain` value is resolved and initialized independently. The dashboard
shows combined data from all monitored domains.

### Custom host and port

```shell
protean observatory --domain auth --host 127.0.0.1 --port 8080
```

### Custom title

```shell
protean observatory --domain auth --title "My App Observatory"
```

### Debug mode

To enable verbose debug logging:

```shell
protean observatory --domain auth --debug
```

You can combine options as needed:

```shell
protean observatory --domain identity --domain catalogue --host 127.0.0.1 --port 3000 --title "ShopStream Observatory" --debug
```

## Endpoints

### Pages

HTML views rendered by the dashboard. See
[Explore your domain in the Observatory](../../../guides/observability/exploring-your-domain.md)
for how to use them.

| Endpoint            | Description                                              |
|---------------------|---------------------------------------------------------|
| `GET /`             | Dashboard home                                          |
| `GET /domain`       | Domain Visualizer (Topology, Event Flows, Process Managers) |
| `GET /timeline`     | Event timeline browser, correlation chains, Traces tab  |
| `GET /eventstore`   | Event store streams view                                |
| `GET /handlers`     | Registered handlers view                                |
| `GET /processes`    | Process manager instances view                          |
| `GET /infrastructure` | Infrastructure status view                            |
| `GET /stream`       | SSE real-time trace events                              |

### API

JSON endpoints, all mounted under `/api`.

| Endpoint                                              | Description                                  |
|------------------------------------------------------|----------------------------------------------|
| `GET /api/health`                                    | Infrastructure health checks                 |
| `GET /api/outbox`                                    | Outbox status per domain                     |
| `GET /api/streams`                                   | Redis stream information                     |
| `GET /api/stats`                                     | Throughput and error rate statistics         |
| `GET /api/domain/ir`                                 | Domain IR transformed into a D3 graph (nodes, links, clusters, flows, stats) |
| `GET /api/timeline/events`                           | Paginated, filterable event list from `$all` |
| `GET /api/timeline/events/{message_id}`              | Single event with full payload and metadata  |
| `GET /api/timeline/stats`                            | Timeline summary statistics                  |
| `GET /api/timeline/correlation/{correlation_id}`     | All events in a correlation chain, with causation tree |
| `GET /api/timeline/aggregate/{stream_category}/{aggregate_id}` | Full event history for one aggregate instance |
| `GET /api/timeline/traces/recent`                    | Most recent correlation chains               |
| `GET /api/timeline/traces/search`                    | Search chains by aggregate / event / command / stream |
| `GET /metrics`                                       | Prometheus text exposition metrics           |
