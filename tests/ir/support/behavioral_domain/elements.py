"""One element of every type whose methods the index tags with a role.

Plain base-class subclasses rather than ``@domain.<element>`` decorators, so the
consuming test registers them onto a fresh domain while their ``__module__`` and
``__qualname__`` keep pointing at this file — which is what both resolution
doors key on.

Deliberate shapes here, each asserted by a test: a private method beside a
public one on the aggregate and the repository, an ``async def`` handler, a
projector using ``@on`` and ``@handle`` side by side, a nested class, and a
decorator that does not reduce to a plain name.
"""

from protean import handle
from protean.core.aggregate import BaseAggregate, apply
from protean.core.command import BaseCommand
from protean.core.command_handler import BaseCommandHandler
from protean.core.event import BaseEvent
from protean.core.event_handler import BaseEventHandler
from protean.core.projection import BaseProjection
from protean.core.projector import BaseProjector, on
from protean.core.repository import BaseRepository
from protean.fields import Identifier, String

#: A decorator reached through a subscript — the trailing-segment rule cannot
#: reduce it to a name, so methods carrying it must come back untagged.
_DECORATORS = {"noop": lambda fn: fn}


class WalletOpened(BaseEvent):
    wallet_id = Identifier(identifier=True)


class FundsDeposited(BaseEvent):
    wallet_id = Identifier(identifier=True)
    amount = String(max_length=10)


class OpenWallet(BaseCommand):
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


class WalletCommandHandler(BaseCommandHandler):
    @handle(OpenWallet)
    def open_wallet(self, command: OpenWallet) -> None:
        """Command-handler method."""

    @_DECORATORS["noop"]
    def audit(self, command: OpenWallet) -> None:
        """Decorator does not reduce to a name, and there is no ``@handle`` —
        untagged, not guessed."""


class WalletEventHandler(BaseEventHandler):
    @handle(FundsDeposited)
    async def on_deposit(self, event: FundsDeposited) -> None:
        """An ``async def`` handler tags exactly like a sync one."""

    def summarise(self) -> None:
        """Public but undecorated — a handler class's plain helper is not a
        handler method."""


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
