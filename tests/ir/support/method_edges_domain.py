"""Fixture module for the ``method_edges`` derivation post-pass (#1433).

The builder derives two behavioral edges by reading method bodies through the
behavioral view, so the elements here live in a real on-disk module: nothing
executes, the derivation only parses the source.

- ``raises`` (aggregates and entities): every event constructed in a method that
  also calls ``raise_`` is recorded, keyed on the called method name so the
  ``user.raise_(...)`` factory idiom counts. It over-reports by co-location — a
  method building two events and raising one records both.
- ``invokes`` (command handlers, event handlers, projectors, process managers): a
  call whose method name matches exactly one method of the elements in scope is
  recorded; an ambiguous name (shared by two elements) is skipped.

``Order`` and its cluster carry every case the acceptance criteria name; the
handlers, process manager and projector each invoke ``Order.place`` to exercise
their own scope resolution. ``Catalog`` is the sparsity control: its one method
neither raises nor invokes, so it carries no ``method_edges`` key at all.
"""

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.entity import BaseEntity
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector
from protean.core.value_object import BaseValueObject
from protean.fields import Identifier, String


class OrderPlaced(BaseEvent):
    order_id = Identifier()


class OrderCancelled(BaseEvent):
    order_id = Identifier()


class OrderShipped(BaseEvent):
    order_id = Identifier()


class OrderDelivered(BaseEvent):
    order_id = Identifier()


class OrderRegistered(BaseEvent):
    order_id = Identifier()


class LineAdjusted(BaseEvent):
    order_id = Identifier()


class OrderTag(BaseValueObject):
    label = String(max_length=20)


class Order(BaseAggregate):
    name = String(max_length=50)

    def place(self):
        # Self-rooted raise of a freshly constructed event: the base case.
        event = OrderPlaced(order_id=self.id)
        self.raise_(event)

    def annotate(self):
        # A value object is built next to the raise; only the event counts.
        tag = OrderTag(label="priority")
        self.raise_(OrderCancelled(order_id=self.id))
        return tag

    def split(self):
        # Two events built, one raised: both recorded (the documented
        # over-report), pinned so it cannot change silently.
        shipped = OrderShipped(order_id=self.id)
        delivered = OrderDelivered(order_id=self.id)
        self.raise_(shipped)
        return delivered

    def preview(self):
        # An event constructed but never raised: no ``raise_``, so no edge.
        return OrderPlaced(order_id=self.id)

    @classmethod
    def register_new(cls, name):
        # The factory idiom: the aggregate is built into a local and the raise
        # goes through it, so the receiver role is UNKNOWN — it still counts.
        order = cls(name=name)
        order.raise_(OrderRegistered(order_id=order.id))
        return order

    def escalate(self, event):
        # Calls ``raise_`` but constructs no event of its own (it re-raises a
        # passed-in one), so co-location finds nothing to record: no edge.
        self.raise_(event)

    def touch(self):
        # A plain method whose name collides with the entity's ``touch``.
        return self.name


class OrderLine(BaseEntity):
    label = String(max_length=50)

    def adjust(self):
        # An entity raises, too: proves the derivation is not aggregate-only.
        self.raise_(LineAdjusted(order_id=self.id))

    def touch(self):
        # Collides with ``Order.touch`` — a handler call to ``touch`` is
        # ambiguous across the cluster and records no edge.
        return self.label


class PlaceOrder(BaseCommand):
    order_id = Identifier()
    name = String()


class TouchOrder(BaseCommand):
    order_id = Identifier()


class OrderCommandHandler(BaseCommandHandler):
    @handle(PlaceOrder)
    def handle_place(self, command):
        # ``place`` matches exactly one cluster method (Order.place): invoked.
        order = Order(name=command.name)
        order.place()

    @handle(TouchOrder)
    def handle_touch(self, command):
        # ``touch`` matches two cluster methods (Order + OrderLine): skipped, so
        # this method carries no edge and is absent from ``method_edges``.
        order = Order(name="x")
        order.touch()
        # A computed callee has no trailing name to look up, so it contributes
        # nothing either. Written here so ``handle_touch`` stays edge-free.
        {"place": order.place}[command.order_id]()


class OrderNotifier(BaseEventHandler):
    @handle(OrderPlaced)
    def on_placed(self, event):
        # An event handler resolves its scope through its own ``part_of``
        # cluster, the same as a command handler.
        order = Order(name="notify")
        order.place()

    @handle(OrderCancelled)
    def on_cancelled(self, event):
        # ``adjust`` is defined only on the OrderLine entity, so this invoke
        # edge names the entity half of the cluster surface, not the aggregate.
        line = OrderLine(label="revised")
        line.adjust()


class OrderProcess(BaseProcessManager):
    order_id = Identifier()
    status = String(default="new")

    @handle(OrderPlaced, start=True, correlate="order_id")
    def on_placed(self, event):
        # A process manager has no ``part_of`` cluster: its scope is the union
        # of the clusters the messages it handles reach (here, Order's).
        self.order_id = event.order_id
        order = Order(name="pm")
        order.place()


class OrderView(BaseProjection):
    order_id = Identifier(identifier=True)
    name = String()


class OrderViewProjector(BaseProjector):
    @handle(OrderPlaced)
    def project_placed(self, event):
        # A projector resolves its scope like a process manager: the union of
        # the clusters of the events it handles.
        order = Order(name="proj")
        order.place()


class Catalog(BaseAggregate):
    """Sparsity control: a method that neither raises nor invokes, so the
    element carries no ``method_edges`` key."""

    title = String(max_length=50)

    def rebuild(self):
        return self.title
