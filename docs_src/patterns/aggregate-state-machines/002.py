from protean import Domain
from protean.fields import String

domain = Domain(name="OrderTransitionMap")


# --8<-- [start:transition_map]
from typing import ClassVar


@domain.aggregate
class Order:
    """
    State machine:

        draft ──place()──→ placed ──pay()──→ paid ──ship()──→ shipped ──deliver()──→ delivered
          │                   │                │
          └──cancel()──→ cancelled        refund()──→ refunded
                              │
                              └──cancel()──→ cancelled
    """

    # Transition map: source_state → {method_name: target_state}
    TRANSITIONS: ClassVar[dict[str, dict[str, str]]] = {
        "draft": {"place": "placed", "cancel": "cancelled"},
        "placed": {"pay": "paid", "cancel": "cancelled"},
        "paid": {"ship": "shipped", "refund": "refunded"},
        "shipped": {"deliver": "delivered"},
        "delivered": {},
        "cancelled": {},
        "refunded": {},
    }
    # --8<-- [end:transition_map]

    status = String(default="draft")
