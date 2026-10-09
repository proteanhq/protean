# --8<-- [start:observatory]
from protean import Domain
from protean.server.observatory import Observatory

domain = Domain(name="Shop")

observatory = Observatory(domains=[domain])

if __name__ == "__main__":
    observatory.run(port=9000)
# --8<-- [end:observatory]
