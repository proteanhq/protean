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
| `--host`    | Host to bind the server to. Loopback by default; see [Security](#security). | `127.0.0.1`           |
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

This will start the dashboard on `http://127.0.0.1:9000` (loopback only). Read
[Domain Discovery](../project/discovery.md) for options to specify the domain.

### Multiple domains

To monitor several domains at once (e.g. in a multi-domain application):

```shell
protean observatory --domain identity --domain catalogue
```

Each `--domain` value is resolved and initialized independently. The dashboard
shows combined data from all monitored domains.

### Custom host and port

To reach the Observatory from another machine you must bind a non-loopback
address explicitly. Do this only on a trusted network; see [Security](#security).

```shell
protean observatory --domain auth --host 0.0.0.0 --port 8080
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

## Security

The Observatory has **no authentication**. It exposes the domain's internal
structure (aggregates, events, handlers, process managers), the full event
stream and correlation chains, and Dead Letter Queue management endpoints that
can **retry or delete messages**. Treat it as a privileged operations console.

- It binds to loopback (`127.0.0.1`) by default, so it is reachable only from
  the local machine.
- To reach it from elsewhere, bind a non-loopback address explicitly
  (`--host 0.0.0.0`). The Observatory logs a warning when it does so.
- Expose it only on a trusted network, and only behind an authenticating
  reverse proxy (or an SSH tunnel / `kubectl port-forward`). Never expose it
  directly to the public internet.
