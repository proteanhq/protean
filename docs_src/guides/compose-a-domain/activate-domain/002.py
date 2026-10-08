from protean import Domain

domain = Domain()
domain.init(traverse=False)

# --8<-- [start:g-resource]
import tempfile

from protean import g


def open_log_file():
    return tempfile.TemporaryFile(mode="w+")


def get_log():
    if "log" not in g:
        g.log = open_log_file()

    return g.log


@domain.teardown_domain_context
def teardown_log_file(exception):
    file_obj = g.pop("log", None)

    if file_obj is not None and not file_obj.closed:
        file_obj.close()


# --8<-- [end:g-resource]
