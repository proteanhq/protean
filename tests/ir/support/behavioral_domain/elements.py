"""One element of every type whose methods the index tags with a role.

Plain base-class subclasses rather than ``@domain.<element>`` decorators, so the
consuming test registers them onto a fresh domain while their ``__module__`` and
``__qualname__`` keep pointing at this file — which is what both resolution
doors key on.

Deliberate shapes here, each asserted by a test: a private method beside a
public one on the aggregate and the repository, an ``async def`` handler, a
private handler method, a projector using ``@on`` and ``@handle`` side by side,
a nested class, an invariant/property/classmethod that must not read as
aggregate behavior, and a decorator that does not reduce to a plain name.
"""

from protean import handle, invariant
from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.event_sourced_repository import BaseEventSourcedRepository
from protean.core.process_manager import BaseProcessManager
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.repository import BaseRepository
from protean.fields import Identifier, String

#: A decorator reached through a subscript — the trailing-segment rule cannot
#: reduce it to a name, so methods carrying it must come back untagged.
_DECORATORS = {"noop": lambda fn: fn}


def audited(fn):
    """A decorator that *does* reduce to a name, and means nothing to the
    index. Used to prove ``@apply`` still wins when another decorator sits
    beside it."""
    return fn


class WalletOpened(BaseEvent):
    wallet_id = Identifier(identifier=True)


class FundsDeposited(BaseEvent):
    wallet_id = Identifier(identifier=True)
    amount = String(max_length=10)


class OpenWallet(BaseCommand):
    wallet_id = Identifier(identifier=True)


class CloseWallet(BaseCommand):
    wallet_id = Identifier(identifier=True)


class Wallet(BaseAggregate):
    wallet_id = Identifier(identifier=True)
    balance = String(max_length=10)

    def rename(self, label: str) -> None:
        """Public, no ``@apply`` — aggregate behavior."""
        self.balance = label

    def _normalize(self) -> None:
        """Private — no role."""

    @apply
    def opened(self, event: WalletOpened) -> None:
        """Event application, not behavior, despite being public."""

    @apply
    @audited
    def deposited(self, event: FundsDeposited) -> None:
        """``@apply`` beside another reducible decorator is still an apply."""

    @invariant.post
    def balance_non_negative(self) -> None:
        """An invariant is not behavior. The trailing-segment rule reads this
        decorator as ``post``, which is why the name-derived roles refuse to
        tag a decorated method at all."""

    @property
    def label(self) -> str:
        """A property is not behavior either."""
        return str(self.wallet_id)

    @classmethod
    def describe(cls) -> str:
        """Nor is a classmethod."""
        return cls.__name__

    def __str__(self) -> str:
        """A dunder is not behavior."""
        return "wallet"

    class Policy:
        """Nested class, reachable as ``Wallet.Policy``, no roles."""

        LIMIT = 10

        def evaluate(self) -> int:
            return self.LIMIT


class WalletRepository(BaseRepository):
    def find_by_label(self, label: str) -> None:
        """Public — repository method."""

    def _cache_key(self, label: str) -> str:
        """Private — no role."""
        return label


class WalletEventSourcedRepository(BaseEventSourcedRepository):
    def find_snapshot(self, wallet_id: str) -> None:
        """Public — a repository method, on the *event-sourced* repository
        type, which is a separate ``DomainObjects`` member."""


class WalletCommandHandler(BaseCommandHandler):
    @handle(OpenWallet)
    def open_wallet(self, command: OpenWallet) -> None:
        """Command-handler method."""

    @on(CloseWallet)
    def close_wallet(self, command: CloseWallet) -> None:
        """``on`` is a literal alias of ``handle``, so this is as much a
        command-handler method as the one above."""

    @_DECORATORS["noop"]
    def audit(self, command: OpenWallet) -> None:
        """Decorator does not reduce to a name, and there is no ``@handle`` —
        untagged, not guessed."""


class WalletEventHandler(BaseEventHandler):
    @handle(FundsDeposited)
    async def on_deposit(self, event: FundsDeposited) -> None:
        """An ``async def`` handler tags exactly like a sync one."""

    @handle(WalletOpened)
    def _audit(self, event: WalletOpened) -> None:
        """A private name does not stop a decorator-derived role: Protean
        registers this as a handler, so the index says it is one."""

    def summarise(self) -> None:
        """Public but undecorated — a handler class's plain helper is not a
        handler method."""


class WalletProcessManager(BaseProcessManager):
    wallet_id = Identifier(identifier=True)

    @handle(WalletOpened, start=True, correlate="wallet_id")
    def on_opened(self, event: WalletOpened) -> None:
        """A process manager handles events with ``@handle`` too, and shares
        the event-handler role — the vocabulary has no separate tag for it."""


class WalletView(BaseProjection):
    wallet_id = Identifier(identifier=True)

    def label(self) -> str:
        """A projection is not in the role vocabulary, so this is untagged
        even though it is public."""
        return str(self.wallet_id)


class WalletProjector(BaseProjector):
    @on(WalletOpened)
    def opened(self, event: WalletOpened) -> None:
        """``on`` is an alias of ``handle``; both read as projector-on-event."""

    @handle(FundsDeposited)
    def deposited(self, event: FundsDeposited) -> None:
        """The same role reached through ``@handle``."""

    def describe(self) -> None:
        """Public but undecorated — not an on-event method."""
