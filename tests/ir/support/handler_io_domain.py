"""Fixture module for HANDLER_PERSISTS_AND_CALLS_OUT.

The rule reads each handler's method bodies through the behavioral view and
flags a method where a `repository_for(...)` call and a call into a known I/O
library both statically resolve. Nothing here executes: the rule only parses the
source, so the HTTP calls never need a server and the repository calls never
need a database.

Both signals must *resolve* for the rule to fire. `repository_for` resolves and
is the persistence signal; the `repo.get(...)` and `repo.add(...)` that follow
resolve to nothing, which is why the rule keys on the former. `AliasedCallOut`
exists to pin that an unresolvable call is skipped rather than guessed at.
"""

import urllib.parse
import urllib.request

import httpx

from protean import handle
from protean.core.aggregate import BaseAggregate
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.process_manager import BaseProcessManager
from protean.fields import Identifier, String
from protean.utils.globals import current_domain

PARTNER_URL = "https://partner.example/orders"


class IoOrder(BaseAggregate):
    name = String(max_length=50)


class IoPlaced(BaseEvent):
    order_id = Identifier()


class PersistsAndCallsOut(BaseEventHandler):
    """Positive: one method does both, so the call runs inside the transaction
    the repository access opened."""

    @handle(IoPlaced)
    def persists_and_calls_out(self, event):
        repo = current_domain.repository_for(IoOrder)
        order = repo.get(event.order_id)
        repo.add(order)
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})


class OnlyCallsOut(BaseEventHandler):
    """Negative: no repository access, so no transaction is open and the call
    costs only wall-clock time."""

    @handle(IoPlaced)
    def notify_partner(self, event):
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})


class OnlyPersists(BaseEventHandler):
    """Negative: a transaction, but nothing reaching outside it."""

    @handle(IoPlaced)
    def record(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="recorded"))


class SplitAcrossSiblings(BaseEventHandler):
    """Negative, and the one that matters most: this is the shape ADR-0031
    tells people to write. Firing here would be the noise the rule exists to
    avoid."""

    @handle(IoPlaced)
    def persist_half(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="split"))

    @handle(IoPlaced)
    def call_out_half(self, event):
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})


class AliasedCallOut(BaseEventHandler):
    """Negative: the call goes through a local alias, so its callee does not
    resolve. Reported as nothing rather than guessed at, which is what keeps
    the verdict reproducible."""

    @handle(IoPlaced)
    def persists_and_calls_indirectly(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="aliased"))
        send = _resolve_sender()
        send(PARTNER_URL, json={"order_id": event.order_id})


def _resolve_sender():
    return httpx.post


class IoFulfillmentPM(BaseProcessManager):
    """Positive, process manager: its dispatch loop wraps each method in its own
    Unit of Work too, so a method that persists and then calls out holds locks
    across the call exactly as an event handler would."""

    order_id = Identifier()
    status = String(default="new")

    @handle(IoPlaced, start=True, correlate="order_id")
    def on_placed(self, event):
        self.order_id = event.order_id
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="pm"))
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})


class BuildsAUrlOnly(BaseEventHandler):
    """Negative: `urllib.parse.urlencode` is rooted in an I/O module but does
    pure string work. Without the verb gate the module alone would flag it."""

    @handle(IoPlaced)
    def record(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="url"))
        urllib.parse.urlencode({"order_id": event.order_id})


class BuildsAClientOnly(BaseEventHandler):
    """Negative: `httpx.Client` is a constructor, not a request."""

    @handle(IoPlaced)
    def record(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="client"))
        httpx.Client()


class CallsOutBeforePersisting(BaseEventHandler):
    """Negative: the call runs before the first repository access, so it is
    outside the transaction. Co-location alone is not the hazard; ordering is."""

    @handle(IoPlaced)
    def record(self, event):
        httpx.post(PARTNER_URL, json={"order_id": event.order_id})
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="before"))


class PersistsThenReachesAnUnambiguousName(BaseEventHandler):
    """Positive through a name in ``UNAMBIGUOUS_IO_NAMES``: `urlopen` reaches the
    network and resolves module-rooted, so it counts on its own."""

    @handle(IoPlaced)
    def record(self, event):
        repo = current_domain.repository_for(IoOrder)
        repo.add(IoOrder(name="urlopen"))
        urllib.request.urlopen(PARTNER_URL)


class PersistsThenCallsOutOnOneLine(BaseEventHandler):
    """Positive: persist and the call share one physical line, the call second.
    Ordering has to use the column, not the line alone, to see it. The one line
    is fenced from the formatter, which would otherwise split the semicolon and
    defeat the point of the case."""

    @handle(IoPlaced)
    def record(self, event):
        # fmt: off
        repo = current_domain.repository_for(IoOrder); httpx.post(PARTNER_URL)  # noqa: E702
        # fmt: on
        repo.add(IoOrder(name="oneline"))
