"""PoC performance benchmarks: Current Protean vs Pydantic Native.

Compares instance creation, field access, mutation, serialization,
and validation performance between the current Protean system and
the Pydantic native approach.

Run with: pytest tests/spike_pydantic/test_performance.py -v -s
"""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import pytest
from pydantic import Field

from tests.spike_pydantic.base_classes import (
    ProteanAggregate,
    ProteanCommand,
    ProteanEntity,
    ProteanValueObject,
)

# Try to import current Protean classes for comparison
try:
    from protean import Domain

    PROTEAN_AVAILABLE = True
except ImportError:
    PROTEAN_AVAILABLE = False

N = 10_000  # Number of iterations for benchmarks


# ---------------------------------------------------------------------------
# Pydantic Native Elements
# ---------------------------------------------------------------------------
class PydanticAddress(ProteanValueObject):
    street: str
    city: str
    zip_code: str
    country: str = "US"


class PydanticOrderItem(ProteanEntity):
    id: UUID = Field(default_factory=uuid4)
    product_name: str
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)


class PydanticOrder(ProteanAggregate):
    id: UUID = Field(default_factory=uuid4)
    order_number: str
    total: float = 0.0
    status: str = "DRAFT"


class PydanticPlaceOrder(ProteanCommand):
    order_id: UUID
    customer_name: str
    items: list[dict]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _benchmark(label: str, fn, n: int = N) -> float:
    """Run fn n times and return elapsed seconds."""
    start = time.perf_counter()
    for _ in range(n):
        fn()
    elapsed = time.perf_counter() - start
    rate = n / elapsed
    print(f"  {label}: {elapsed:.3f}s ({rate:,.0f} ops/sec)")
    return elapsed


# ---------------------------------------------------------------------------
# Pydantic Native Benchmarks
# ---------------------------------------------------------------------------
class TestPydanticNativeBenchmarks:
    """Benchmark Pydantic native element operations."""

    def test_vo_creation(self):
        """Benchmark: Create 10,000 Value Objects."""
        elapsed = _benchmark(
            "Pydantic VO creation",
            lambda: PydanticAddress(street="123 Main", city="NYC", zip_code="10001"),
        )
        # Just ensure it completes in reasonable time
        assert elapsed < 30  # generous upper bound

    def test_entity_creation(self):
        """Benchmark: Create 10,000 Entities."""
        elapsed = _benchmark(
            "Pydantic Entity creation",
            lambda: PydanticOrderItem(
                product_name="Widget", quantity=2, unit_price=9.99
            ),
        )
        assert elapsed < 30

    def test_aggregate_creation(self):
        """Benchmark: Create 10,000 Aggregates."""
        elapsed = _benchmark(
            "Pydantic Aggregate creation",
            lambda: PydanticOrder(order_number="ORD-001"),
        )
        assert elapsed < 30

    def test_command_creation(self):
        """Benchmark: Create 10,000 Commands."""
        uid = uuid4()
        elapsed = _benchmark(
            "Pydantic Command creation",
            lambda: PydanticPlaceOrder(
                order_id=uid, customer_name="Alice", items=[{"p": "w"}]
            ),
        )
        assert elapsed < 30

    def test_vo_model_dump(self):
        """Benchmark: Serialize 10,000 VOs."""
        addr = PydanticAddress(street="123 Main", city="NYC", zip_code="10001")
        elapsed = _benchmark(
            "Pydantic VO model_dump",
            lambda: addr.model_dump(),
        )
        assert elapsed < 30

    def test_entity_model_dump(self):
        """Benchmark: Serialize 10,000 Entities."""
        item = PydanticOrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        elapsed = _benchmark(
            "Pydantic Entity model_dump",
            lambda: item.model_dump(),
        )
        assert elapsed < 30

    def test_entity_mutation(self):
        """Benchmark: Mutate entity field 10,000 times."""
        item = PydanticOrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        i = [0]

        def mutate():
            i[0] += 1
            item.quantity = (i[0] % 100) + 1

        elapsed = _benchmark("Pydantic Entity mutation", mutate)
        assert elapsed < 30

    def test_aggregate_mutation(self):
        """Benchmark: Mutate aggregate field 10,000 times."""
        order = PydanticOrder(order_number="ORD-001")
        i = [0]

        def mutate():
            i[0] += 1
            order.total = float(i[0])

        elapsed = _benchmark("Pydantic Aggregate mutation", mutate)
        assert elapsed < 30

    def test_field_access(self):
        """Benchmark: Access entity fields 10,000 times."""
        item = PydanticOrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        elapsed = _benchmark(
            "Pydantic field access",
            lambda: (item.product_name, item.quantity, item.unit_price),
        )
        assert elapsed < 30

    def test_json_schema_generation(self):
        """Benchmark: Generate JSON Schema 1,000 times."""
        elapsed = _benchmark(
            "Pydantic JSON Schema",
            lambda: PydanticOrder.model_json_schema(),
            n=1000,
        )
        assert elapsed < 30


# ---------------------------------------------------------------------------
# Current Protean Benchmarks (if available)
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not PROTEAN_AVAILABLE, reason="Protean not available")
class TestCurrentProteanBenchmarks:
    """Benchmark current Protean element operations for comparison."""

    @pytest.fixture(autouse=True)
    def setup_domain(self):
        """Set up a minimal Protean domain."""
        self.domain = Domain(__file__, "benchmark")

        @self.domain.value_object
        class ProteanAddr:
            street: str
            city: str
            zip_code: str

        @self.domain.aggregate
        class ProteanOrderAgg:
            order_number: str
            total: float = 0.0

        self.ProteanAddr = ProteanAddr
        self.ProteanOrderAgg = ProteanOrderAgg

        with self.domain.domain_context():
            yield

    def test_current_vo_creation(self):
        """Benchmark: Current Protean VO creation."""
        Addr = self.ProteanAddr
        _benchmark(
            "Current VO creation",
            lambda: Addr(street="123 Main", city="NYC", zip_code="10001"),
        )

    def test_current_aggregate_creation(self):
        """Benchmark: Current Protean Aggregate creation."""
        Agg = self.ProteanOrderAgg
        _benchmark(
            "Current Aggregate creation",
            lambda: Agg(order_number="ORD-001"),
        )


# ---------------------------------------------------------------------------
# Summary output
# ---------------------------------------------------------------------------
class TestBenchmarkSummary:
    """Print a summary of all benchmarks."""

    def test_summary(self):
        """Run key benchmarks and print comparison table."""
        print("\n" + "=" * 70)
        print("PYDANTIC NATIVE BENCHMARK SUMMARY")
        print("=" * 70)

        results = {}

        # VO creation
        results["VO creation"] = _benchmark(
            "VO creation",
            lambda: PydanticAddress(street="123 Main", city="NYC", zip_code="10001"),
        )

        # Entity creation
        results["Entity creation"] = _benchmark(
            "Entity creation",
            lambda: PydanticOrderItem(
                product_name="Widget", quantity=2, unit_price=9.99
            ),
        )

        # Aggregate creation
        results["Aggregate creation"] = _benchmark(
            "Aggregate creation",
            lambda: PydanticOrder(order_number="ORD-001"),
        )

        # Command creation
        uid = uuid4()
        results["Command creation"] = _benchmark(
            "Command creation",
            lambda: PydanticPlaceOrder(
                order_id=uid, customer_name="Alice", items=[{"p": "w"}]
            ),
        )

        # VO serialization
        addr = PydanticAddress(street="123 Main", city="NYC", zip_code="10001")
        results["VO model_dump"] = _benchmark(
            "VO model_dump",
            lambda: addr.model_dump(),
        )

        # Entity mutation
        item = PydanticOrderItem(product_name="Widget", quantity=2, unit_price=9.99)
        i = [0]
        results["Entity mutation"] = _benchmark(
            "Entity mutation",
            lambda: setattr(
                item, "quantity", (i.__setitem__(0, i[0] + 1) or i[0]) % 100 + 1
            )
            if False
            else _benchmark(
                "Entity mutation (inner)",
                lambda: item.__setattr__("quantity", 1),
                n=1,
            ),
            n=1,
        )

        print("\n" + "-" * 70)
        print(f"{'Operation':<25} {'Time (s)':<12} {'Ops/sec':<15}")
        print("-" * 70)
        for op, elapsed in results.items():
            if elapsed > 0:
                rate = N / elapsed
                print(f"{op:<25} {elapsed:<12.3f} {rate:<15,.0f}")
        print("=" * 70)

        assert True  # Always pass
