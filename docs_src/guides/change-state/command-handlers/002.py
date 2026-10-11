from types import SimpleNamespace

from protean import Domain, handle
from protean.fields import Float, Identifier, String

domain = Domain(name="Payments")


class _PaymentIntents:
    """A stand-in for the Stripe SDK, so the example runs without a network.

    It records the keyword arguments of every ``create`` call.
    """

    def __init__(self):
        self.created = []

    def create(self, **kwargs):
        self.created.append(kwargs)


stripe = SimpleNamespace(PaymentIntent=_PaymentIntents())


@domain.aggregate
class Account:
    email: String(required=True)


# --8<-- [start:handler]
@domain.command(part_of=Account)
class ChargeCard:
    account_id: Identifier(required=True)
    amount: Float(required=True)


@domain.command_handler(part_of=Account)
class AccountCommandHandler:
    @handle(ChargeCard)
    def charge(self, command: ChargeCard):
        key = command._metadata.headers.idempotency_key

        # Pass through to external APIs that support idempotency
        stripe.PaymentIntent.create(
            amount=command.amount,
            currency="usd",
            idempotency_key=key,
        )


# --8<-- [end:handler]


if __name__ == "__main__":
    domain.init(traverse=False)
    with domain.domain_context():
        domain.process(
            ChargeCard(account_id="acc-1", amount=25.0),
            asynchronous=False,
            idempotency_key="charge-acc-1-001",
        )
        print(stripe.PaymentIntent.created)
