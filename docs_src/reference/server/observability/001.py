# --8<-- [start:domains]
from protean import Domain

identity = Domain(name="identity")
catalogue = Domain(name="catalogue")
# --8<-- [end:domains]

# --8<-- [start:app]
from protean.server.observatory import create_observatory_app

app = create_observatory_app(domains=[identity, catalogue])

# Then run with: uvicorn my_module:app --host 0.0.0.0 --port 9000
# --8<-- [end:app]
