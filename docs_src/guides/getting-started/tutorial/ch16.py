# --8<-- [start:uuid_import]
import uuid

# --8<-- [end:uuid_import]
from bookshelf import domain
from bookshelf.commands import AddBook


# --8<-- [start:correlation]
def add_traced_book() -> str:
    trace_id = str(uuid.uuid4())
    domain.process(
        AddBook(title="Dune", author="Frank Herbert", price_amount=15.99),
        correlation_id=trace_id,
    )
    return trace_id


# --8<-- [end:correlation]
# --8<-- [start:programmatic]
from protean.port.event_store import CausationNode
from protean.utils.globals import current_domain


def print_trace(correlation_id: str) -> CausationNode | None:
    # The tree starts at the first command that carried the correlation ID
    store = current_domain.event_store.store
    tree = store.build_causation_tree(correlation_id)

    def show(node: CausationNode, depth: int = 0) -> None:
        print(f"{'  ' * depth}{node.message_type} ({node.kind})")
        for child in node.children:
            show(child, depth + 1)

    if tree is not None:
        show(tree)
    return tree


# --8<-- [end:programmatic]
