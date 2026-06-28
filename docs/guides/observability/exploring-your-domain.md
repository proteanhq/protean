# Explore your domain in the Observatory

The Protean Observatory ships two interactive views that turn a running domain
into something you can navigate: a **Domain Visualizer** that draws your
aggregates and their relationships from the live IR, and a **Timeline** that
lets you browse, filter, and trace every message the system has processed.

This guide covers how to use both. For startup options and the full endpoint
list see the [`protean observatory` reference](../../reference/cli/runtime/observatory.md);
for the tracing data behind the views see
[Correlation and causation IDs](correlation-and-causation.md).

Start the Observatory and open it in a browser:

```bash
protean observatory --domain=myapp
# Visit http://localhost:8080
```

---

## Visualize the domain topology

Open the **Domain** page (`/domain`). It renders directly from the domain's
[Intermediate Representation](../compose-a-domain/inspecting-the-ir.md), so the
picture never drifts from the code: what you see is what is registered. Three
tabs slice the same model:

- **Topology** draws an interactive, force-directed graph of your aggregates.
  Each node shows the aggregate name, its stream category, an ES/CQRS badge,
  and element counts; directed edges connect aggregates linked by
  cross-aggregate event handlers and process managers. Zoom, pan, and drag
  nodes to lay the graph out; hover a node to highlight everything it connects
  to, and use the mini-map to navigate large domains.
- **Event Flows** shows the command-to-event-to-handler chains as a directed
  graph, grouped by cluster, with element-type filters for narrowing to just
  commands, events, or handlers.
- **Process Managers** renders each process manager as a state machine
  alongside a summary of the domain's elements.

Click any aggregate to open the **detail panel**, a slide-in view with
collapsible sections for its fields, entities, value objects, commands, events,
handlers, invariants, and repository/models.

---

## Browse and trace the timeline

Open the **Timeline** page (`/timeline`) to walk the event store
chronologically. The filter bar narrows the stream by stream category, event
type, command type, aggregate ID, and kind; results page in as you scroll. Each
row opens a detail panel with the full payload and metadata, plus links into
the message's correlation chain and aggregate history.

Two sub-views drill in from there:

- **Correlation chain** renders the causation tree for a `correlation_id` as a
  vertical graph, with handler attribution, per-step latencies, and
  cross-aggregate boundary markers. Deep-link straight to it with
  `?correlation=<id>`.
- **Aggregate history** lists one aggregate instance's events in order with
  version labels. Deep-link with `?stream=<category>&aggregate=<id>`.

The **Traces** tab searches recent correlation chains by aggregate ID, event
type, command type, or stream category, and links each result to its chain
view. When the domain is actively processing, both the timeline and the
correlation graph update live over SSE: new events animate in and the summary
stat cards refresh without a reload.

!!! tip "Find a request from its correlation ID"
    Every HTTP response carries an `X-Correlation-ID` header. Paste that value
    into the Traces search (or `?correlation=<id>`) to jump straight to the
    full causal chain for that request.

---

## See also

- [`protean observatory` reference](../../reference/cli/runtime/observatory.md):
  CLI options and the complete endpoint catalog.
- [Correlation and causation IDs](correlation-and-causation.md): how the
  chains the Timeline draws are propagated and assembled.
- [Monitoring](../server/monitoring.md): metrics, subscription lag, and
  Prometheus scraping for the same server.
