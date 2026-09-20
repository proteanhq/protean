# API Endpoint Anti-patterns

Common mistakes when implementing API endpoints in Protean and how to avoid them.

## 1. Business Logic in the Endpoint

**Wrong:**
```python
@app.post("/orders")
async def create_order(request: Request):
    payload = await request.json()
    if payload["total_amount"] <= 0:
        return JSONResponse(status_code=400, content={"error": "Invalid amount"})
    if payload["total_amount"] > 10000:
        return JSONResponse(status_code=400, content={"error": "Amount too high"})
    command = PlaceOrder(...)
    current_domain.process(command, asynchronous=False)
```

**Correct:** Business rules belong in the aggregate. The endpoint only constructs the command.

```python
@app.post("/orders", status_code=201)
async def create_order(request: Request):
    payload = await request.json()
    command = PlaceOrder(
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
        total_amount=payload["total_amount"],
    )
    result = current_domain.process(command, asynchronous=False)
    return JSONResponse(status_code=201, content={"order_id": result})
```

The aggregate's `place()` method enforces amount rules.

## 2. Direct Repository Access

**Wrong:**
```python
@app.post("/orders")
async def create_order(request: Request):
    payload = await request.json()
    order = Order(
        order_id=payload["order_id"],
        customer_id=payload["customer_id"],
    )
    order.place(total_amount=payload["total_amount"])
    current_domain.repository_for(Order).add(order)  # Direct repo access!
```

**Correct:** Always go through `domain.process()`. The endpoint constructs a command and lets the domain handle persistence.

## 3. Missing Domain Context Middleware

**Wrong:**
```python
app = FastAPI()

@app.post("/orders")
async def create_order(request: Request):
    current_domain.process(command)  # Fails! No domain context
```

**Correct:** Always register domain context middleware.

```python
app = FastAPI()

@app.middleware("http")
async def domain_context_middleware(request: Request, call_next):
    with domain.domain_context():
        response = await call_next(request)
    return response
```

## 4. Calling Handlers Directly

**Wrong:**
```python
@app.post("/orders")
async def create_order(request: Request):
    handler = OrderCommandHandler()
    handler.handle_place_order(command)  # Bypasses domain.process!
```

**Correct:** Always use `current_domain.process(command)`. Direct handler invocation bypasses command enrichment, event store persistence, and the UnitOfWork.

## 5. Importing Domain Instead of Using current_domain

**Wrong:**
```python
from my_app import domain  # Module-level import

@app.post("/orders")
async def create_order(request: Request):
    domain.process(command)  # Uses module-level reference
```

**Correct:** Use `current_domain` from globals, which is set by the domain context middleware.

```python
from protean.utils.globals import current_domain

@app.post("/orders")
async def create_order(request: Request):
    current_domain.process(command)  # Uses context-local domain
```

## 6. Mixing Pydantic and Domain Validation

**Wrong:**
```python
class OrderRequest(BaseModel):
    total_amount: float = Field(..., gt=0, lt=10000)  # Business rule in Pydantic!
```

**Correct:** Pydantic validates format (types, required fields, email format). Business rules (amount limits, status transitions) belong in the aggregate.

```python
class OrderRequest(BaseModel):
    total_amount: float  # Only type validation at boundary
```

## 7. Fat Endpoints with Multiple Operations

**Wrong:**
```python
@app.post("/orders")
async def create_order(request: Request):
    payload = await request.json()
    order_cmd = PlaceOrder(...)
    current_domain.process(order_cmd, asynchronous=False)
    # Also update inventory!
    inventory_cmd = ReserveStock(...)
    current_domain.process(inventory_cmd, asynchronous=False)
```

**Correct:** One endpoint, one command. Cross-aggregate coordination happens via domain events, not in endpoints.

## Related

- [Request Validation](./request-validation.md) - Proper validation patterns
- [Response Patterns](./response-patterns.md) - HTTP response guidelines
- [command-handler anti-patterns](../../command-handler/references/anti-patterns.md) - Handler-level mistakes
