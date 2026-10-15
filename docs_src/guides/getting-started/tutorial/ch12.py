from bookshelf import domain
from bookshelf.commands import AddBook


# --8<-- [start:queue_book]
def queue_book() -> None:
    # This returns immediately: the command is queued
    domain.process(AddBook(title="Gatsby", author="Fitzgerald", price_amount=12.99))


# --8<-- [end:queue_book]
