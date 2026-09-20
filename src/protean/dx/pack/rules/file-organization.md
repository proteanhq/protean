---
description: File organization patterns — screaming architecture, file naming, and co-location rules for Protean projects
globs: "**/*.py"
---

# File Organization

## Screaming Architecture

Organize by **domain concept** (aggregates, bounded contexts), not by **technical type**
(commands/, events/, handlers/). A new developer should see the business domain, not
the framework:

```
src/ecommerce/
├── order/              # Aggregate folder
│   ├── order.py        # Aggregate + entities + VOs
│   ├── place_order.py  # Command + Command Handler (colocated)
│   ├── order_placed.py # Event
│   └── order_api.py    # FastAPI endpoints
├── inventory/
│   ├── stock.py
│   └── handle_order_placed.py  # Cross-aggregate event handler
└── domain.py           # Domain instance
```

## File Naming

| File pattern | Contains |
|-------------|----------|
| `order.py` | Aggregate + entities + value objects |
| `place_order.py` | Command + command handler (colocated by action) |
| `order_placed.py` | Event (+ same-aggregate event handler if simple) |
| `handle_order_placed.py` | Cross-aggregate event handler (in target aggregate's folder) |
| `order_api.py` | FastAPI endpoints for this aggregate |

## Co-location Rules

- **Command + handler** belong in the same file, named after the action (`place_order.py`)
- **Cross-aggregate event handlers** go in the **target** aggregate's folder, not the source
- **Value objects** shared across aggregates go in a `shared/` folder
- **Value objects** used by one aggregate go in that aggregate's file
