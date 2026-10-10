from protean import Domain

domain = Domain(name="Tooling")


def do_the_work() -> None: ...


# --8<-- [start:close]
def run_tool():
    try:
        with domain.domain_context():
            do_the_work()
    finally:
        domain.close()


# --8<-- [end:close]
