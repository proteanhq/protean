# Event Processing

Subscribers consume external broker messages, process managers coordinate
multi-step workflows, and upcasters convert stored event data from an older
schema version to a newer one.

**Guides:**
[Subscribers](../guides/consume-state/subscribers.md) ·
[Process Managers](../guides/consume-state/process-managers.md) ·
[Event Upcasting](../guides/consume-state/event-upcasting.md)

---

::: protean.core.subscriber.BaseSubscriber
    options:
      inherited_members: false

---

::: protean.core.process_manager.BaseProcessManager
    options:
      inherited_members: false

---

::: protean.core.upcaster.BaseUpcaster
    options:
      inherited_members: false
