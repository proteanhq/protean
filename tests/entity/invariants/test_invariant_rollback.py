"""A failed post-invariant undoes the assignment that broke it."""

import pytest

from protean.core.aggregate import BaseAggregate, atomic_change
from protean.core.entity import BaseEntity, invariant
from protean.core.event import BaseEvent
from protean.core.value_object import BaseValueObject
from protean.exceptions import ValidationError
from protean.fields import (
    Dict,
    Float,
    HasMany,
    HasOne,
    Integer,
    List,
    Reference,
    String,
    ValueObject,
)


class Money(BaseValueObject):
    amount: Float()
    currency: String(max_length=3)


class Account(BaseAggregate):
    name: String(max_length=50)
    balance: Float(default=0.0)
    nickname: String(max_length=50)
    limit = ValueObject(Money)

    @invariant.pre
    def name_must_not_be_frozen(self):
        if self.name == "frozen":
            raise ValidationError({"_entity": ["Account is frozen"]})

    @invariant.post
    def balance_must_not_be_negative(self):
        if self.balance is not None and self.balance < 0:
            raise ValidationError({"balance": ["Balance cannot be negative"]})

    @invariant.post
    def nickname_must_not_be_reserved(self):
        if self.nickname == "admin":
            raise ValidationError({"nickname": ["Nickname is reserved"]})

    @invariant.post
    def limit_must_not_be_negative(self):
        if self.limit is not None and self.limit.amount < 0:
            raise ValidationError({"limit": ["Limit cannot be negative"]})

    def withdraw(self, amount: float) -> None:
        self.balance -= amount

    def rename_and_withdraw(self, name: str, amount: float) -> None:
        self.name = name
        self.balance -= amount


class AccountRenamed(BaseEvent):
    name: String(max_length=50)


class Order(BaseAggregate):
    total: Float(default=0.0)
    items = HasMany("OrderItem")
    note = HasOne("OrderNote")

    @invariant.post
    def total_must_match_items(self):
        if self.total != sum(item.quantity * item.price for item in self.items):
            raise ValidationError({"_entity": ["Total must match the items"]})

    @invariant.post
    def note_must_not_be_blank(self):
        if self.note is not None and self.note.text == "":
            raise ValidationError({"_entity": ["Note cannot be blank"]})


class OrderItem(BaseEntity):
    quantity: Integer()
    price: Float()


class OrderNote(BaseEntity):
    text: String(max_length=100)


class Customer(BaseAggregate):
    name: String(max_length=50)


class Invoice(BaseAggregate):
    amount: Float()
    customer = Reference(Customer)

    @invariant.post
    def blocked_customer_cannot_be_billed(self):
        if self.customer is not None and self.customer.name == "blocked":
            raise ValidationError({"customer": ["Customer is blocked"]})

    @invariant.post
    def large_invoice_needs_a_customer(self):
        if self.amount is not None and self.amount > 100 and self.customer is None:
            raise ValidationError({"customer": ["Large invoices need a customer"]})


class CreditLine(BaseAggregate):
    limit = ValueObject(Money)

    @invariant.post
    def limit_is_required(self):
        if self.limit is None:
            raise ValidationError({"limit": ["Limit is required"]})


class Basket(BaseAggregate):
    lines = HasMany("BasketLine")

    @invariant.post
    def must_have_a_line(self):
        if not self.lines:
            raise ValidationError({"_entity": ["Basket needs a line"]})

    @invariant.post
    def line_price_must_not_be_negative(self):
        for line in self.lines:
            if line.price is not None and line.price.amount < 0:
                raise ValidationError({"_entity": ["Price cannot be negative"]})


class BasketLine(BaseEntity):
    price = ValueObject(Money)
    tags = HasMany("LineTag")


class LineTag(BaseEntity):
    label: String(max_length=20)


class Score(BaseAggregate):
    points: Integer()

    @invariant.post
    def points_must_not_be_negative(self):
        # Fails with TypeError when points is None.
        if self.points < 0:
            raise ValidationError({"points": ["Points cannot be negative"]})


class Playlist(BaseAggregate):
    tags = List(content_type=String)
    settings = Dict()

    @invariant.post
    def tags_must_not_be_banned(self):
        if "banned" in (self.tags or []):
            raise ValidationError({"tags": ["Tag is banned"]})


@pytest.fixture(autouse=True)
def register_elements(test_domain):
    test_domain.register(Money)
    test_domain.register(Account)
    test_domain.register(AccountRenamed, part_of=Account)
    test_domain.register(Order)
    test_domain.register(OrderItem, part_of=Order)
    test_domain.register(OrderNote, part_of=Order)
    test_domain.register(Customer)
    test_domain.register(Invoice)
    test_domain.register(CreditLine)
    test_domain.register(Basket)
    test_domain.register(BasketLine, part_of=Basket)
    test_domain.register(LineTag, part_of=BasketLine)
    test_domain.register(Score)
    test_domain.register(Playlist)
    test_domain.init(traverse=False)


@pytest.fixture
def account():
    account = Account(name="Main", balance=10.0)
    account.state_.mark_saved()
    return account


@pytest.fixture
def order():
    order = Order(
        total=20.0,
        items=[OrderItem(quantity=2, price=5.0), OrderItem(quantity=1, price=10.0)],
        note=OrderNote(text="Leave at the door"),
    )
    order.state_.mark_saved()
    for item in order.items:
        item.state_.mark_saved()
    order.note.state_.mark_saved()
    return order


class TestDirectAssignmentRollsBack:
    def test_failed_assignment_keeps_the_old_value(self, account):
        with pytest.raises(ValidationError) as exc:
            account.balance = -5.0

        assert exc.value.messages == {"balance": ["Balance cannot be negative"]}
        assert account.balance == 10.0

    def test_failed_assignment_does_not_mark_the_aggregate_changed(self, account):
        with pytest.raises(ValidationError):
            account.balance = -5.0

        assert account.state_.is_changed is False

    def test_serialized_forms_show_the_old_value(self, account):
        with pytest.raises(ValidationError):
            account.balance = -5.0

        assert account.to_dict()["balance"] == 10.0
        assert account.model_dump()["balance"] == 10.0

    def test_never_set_field_returns_to_unset(self, account):
        assert "nickname" not in account.model_fields_set

        with pytest.raises(ValidationError):
            account.nickname = "admin"

        assert account.nickname is None
        assert "nickname" not in account.model_fields_set
        assert "nickname" not in account.model_dump(exclude_unset=True)

    def test_a_second_assignment_after_rollback_still_validates(self, account):
        with pytest.raises(ValidationError):
            account.balance = -5.0

        account.balance = 3.0

        assert account.balance == 3.0
        assert account.state_.is_changed is True


class TestAssignmentInsideAMethodRollsBack:
    def test_failed_method_assignment_keeps_the_old_value(self, account):
        with pytest.raises(ValidationError):
            account.withdraw(15.0)

        assert account.balance == 10.0
        assert account.state_.is_changed is False

    def test_earlier_passing_assignment_stays_applied(self, account):
        with pytest.raises(ValidationError):
            account.rename_and_withdraw("Savings", 15.0)

        assert account.name == "Savings"
        assert account.balance == 10.0
        # The rename passed its own post-check and marked the aggregate changed.
        assert account.state_.is_changed is True


class TestChildEntityAssignmentRollsBack:
    def test_has_many_child_field_keeps_the_old_value(self, order):
        item = order.items[0]

        with pytest.raises(ValidationError) as exc:
            item.quantity = 3

        assert exc.value.messages == {"_entity": ["Total must match the items"]}
        assert item.quantity == 2
        assert item.state_.is_changed is False
        assert order.state_.is_changed is False
        assert order.to_dict()["items"][0]["quantity"] == 2

    def test_has_one_child_field_keeps_the_old_value(self, order):
        with pytest.raises(ValidationError) as exc:
            order.note.text = ""

        assert exc.value.messages == {"_entity": ["Note cannot be blank"]}
        assert order.note.text == "Leave at the door"
        assert order.note.state_.is_changed is False


class TestValueObjectAssignmentRollsBack:
    def test_value_object_and_shadow_attributes_keep_old_values(self, account):
        old_limit = Money(amount=100.0, currency="USD")
        account.limit = old_limit
        account.state_.mark_saved()

        with pytest.raises(ValidationError) as exc:
            account.limit = Money(amount=-1.0, currency="EUR")

        assert exc.value.messages == {"limit": ["Limit cannot be negative"]}
        assert account.limit is old_limit
        assert account.limit_amount == 100.0
        assert account.limit_currency == "USD"
        assert account.state_.is_changed is False
        assert account.to_dict()["limit"] == {"amount": 100.0, "currency": "USD"}

    def test_never_set_value_object_returns_to_unset(self, account):
        keys = ("limit", "limit_amount", "limit_currency")
        before = {key: account.__dict__.get(key, "<absent>") for key in keys}

        with pytest.raises(ValidationError):
            account.limit = Money(amount=-1.0, currency="EUR")

        assert account.limit is None
        assert {key: account.__dict__.get(key, "<absent>") for key in keys} == before
        assert account.state_.is_changed is False


class TestReferenceAssignmentRollsBack:
    def test_reference_and_its_id_attribute_keep_old_values(self):
        good = Customer(name="Good")
        blocked = Customer(name="blocked")
        invoice = Invoice(amount=10.0, customer=good)
        invoice.state_.mark_saved()

        with pytest.raises(ValidationError) as exc:
            invoice.customer = blocked

        assert exc.value.messages == {"customer": ["Customer is blocked"]}
        assert invoice.customer is good
        assert invoice.customer_id == good.id
        assert invoice.state_.is_changed is False

    def test_never_set_reference_returns_to_unset(self):
        blocked = Customer(name="blocked")
        invoice = Invoice(amount=10.0)
        invoice.state_.mark_saved()

        with pytest.raises(ValidationError):
            invoice.customer = blocked

        assert invoice.customer is None
        assert invoice.customer_id is None
        assert invoice.state_.is_changed is False

    def test_reference_set_to_none_keeps_old_values(self):
        good = Customer(name="Good")
        invoice = Invoice(amount=500.0, customer=good)
        invoice.state_.mark_saved()

        with pytest.raises(ValidationError) as exc:
            invoice.customer = None

        assert exc.value.messages == {"customer": ["Large invoices need a customer"]}
        assert invoice.customer is good
        assert invoice.customer_id == good.id
        assert invoice.state_.is_changed is False


class TestValueObjectSetToNoneRollsBack:
    def test_value_object_set_to_none_keeps_old_values(self):
        old_limit = Money(amount=50.0, currency="USD")
        credit = CreditLine(limit=old_limit)
        credit.state_.mark_saved()

        with pytest.raises(ValidationError):
            credit.limit = None

        assert credit.limit is old_limit
        assert credit.limit_amount == 50.0
        assert credit.state_.is_changed is False


@pytest.fixture
def basket():
    basket = Basket(
        lines=[
            BasketLine(
                price=Money(amount=5.0, currency="USD"),
                tags=[LineTag(label="gift")],
            )
        ]
    )
    basket.state_.mark_saved()
    return basket


class TestAssociationAssignmentRollsBack:
    def test_has_one_assignment_keeps_the_old_child(self, order):
        old_note = order.note
        changes_before = order._temp_cache["note"].change

        with pytest.raises(ValidationError) as exc:
            order.note = OrderNote(text="")

        assert exc.value.messages == {"_entity": ["Note cannot be blank"]}
        assert order.note is old_note
        assert order.note.text == "Leave at the door"
        assert order._temp_cache["note"].change == changes_before
        assert order.state_.is_changed is False

    def test_never_assigned_has_one_returns_to_unset(self):
        order = Order(total=0.0)
        order.state_.mark_saved()
        assert "note" not in order._temp_cache

        with pytest.raises(ValidationError):
            order.note = OrderNote(text="")

        assert order.note is None
        assert "note" not in order._temp_cache
        assert order.state_.is_changed is False

    def test_has_many_assignment_keeps_the_old_children(self, order):
        old_items = list(order.items)
        added_before = dict(order._temp_cache["items"].added)

        with pytest.raises(ValidationError):
            order.items = [OrderItem(quantity=1, price=1.0)]

        assert order.items == old_items
        assert order._temp_cache["items"].added == added_before
        assert order.state_.is_changed is False

    def test_has_many_assignment_to_empty_list_keeps_the_children(self, order):
        old_items = list(order.items)

        with pytest.raises(ValidationError):
            order.items = []

        assert order.items == old_items
        assert order._temp_cache["items"].removed == {}

    def test_failed_add_keeps_the_old_children(self, order):
        old_items = list(order.items)

        with pytest.raises(ValidationError):
            order.add_items(OrderItem(quantity=1, price=1.0))

        assert order.items == old_items
        assert len(order._temp_cache["items"].added) == 2

    def test_failed_remove_keeps_the_children(self, order):
        old_items = list(order.items)

        with pytest.raises(ValidationError):
            order.remove_items(order.items[0])

        assert order.items == old_items
        assert order._temp_cache["items"].removed == {}

    def test_failed_remove_keeps_the_grandchildren(self, basket):
        line = basket.lines[0]
        tag = line.tags[0]

        with pytest.raises(ValidationError) as exc:
            basket.remove_lines(line)

        assert exc.value.messages == {"_entity": ["Basket needs a line"]}
        assert basket.lines == [line]
        assert line.tags == [tag]
        assert line._temp_cache["tags"].removed == {}

    def test_rejected_has_one_child_is_left_unlinked(self, order):
        rejected = OrderNote(text="")

        with pytest.raises(ValidationError):
            order.note = rejected

        assert rejected._root is None
        assert rejected._owner is None
        assert rejected.order_id is None
        assert rejected.__dict__.get("order") is None

    def test_rejected_has_many_child_is_left_unlinked(self, order):
        rejected = OrderItem(quantity=1, price=1.0)

        with pytest.raises(ValidationError):
            order.add_items(rejected)

        assert rejected._root is None
        assert rejected._owner is None
        assert rejected.order_id is None

    def test_successful_add_and_remove_still_apply(self, order):
        new_item = OrderItem(quantity=0, price=1.0)

        order.add_items(new_item)
        assert new_item in order.items

        order.remove_items(new_item)
        assert new_item not in order.items


class TestValueObjectOnChildEntityRollsBack:
    def test_child_value_object_keeps_the_old_value(self, basket):
        line = basket.lines[0]
        old_price = line.price
        line.state_.mark_saved()

        with pytest.raises(ValidationError) as exc:
            line.price = Money(amount=-1.0, currency="USD")

        assert exc.value.messages == {"_entity": ["Price cannot be negative"]}
        assert line.price is old_price
        assert line.price_amount == 5.0
        assert line.state_.is_changed is False


class TestNonValidationErrorRollsBack:
    def test_invariant_raising_another_error_still_undoes_the_assignment(self):
        score = Score(points=1)
        score.state_.mark_saved()

        with pytest.raises(TypeError):
            score.points = None

        assert score.points == 1
        assert score.state_.is_changed is False

        score.points = 2
        assert score.points == 2


class TestControls:
    def test_valid_assignment_applies_and_marks_changed(self, account):
        account.balance = 4.0

        assert account.balance == 4.0
        assert account.state_.is_changed is True

    def test_pre_check_failure_leaves_the_value_untouched(self):
        account = Account(name="frozen", balance=10.0)
        account.state_.mark_saved()

        with pytest.raises(ValidationError) as exc:
            account.balance = 4.0

        assert exc.value.messages == {"_entity": ["Account is frozen"]}
        assert account.balance == 10.0
        assert account.state_.is_changed is False

    def test_type_error_leaves_the_value_untouched(self, account):
        with pytest.raises(ValidationError) as exc:
            account.balance = "not a number"

        assert "balance" in exc.value.messages
        assert account.balance == 10.0
        assert account.state_.is_changed is False


class TestAtomicChangeRollsBack:
    def test_fields_changed_in_the_block_return_to_block_entry(self, account):
        with pytest.raises(ValidationError):
            with atomic_change(account):
                account.name = "Renamed"
                account.balance = -5.0

        assert account.name == "Main"
        assert account.balance == 10.0
        assert account.state_.is_changed is False

    def test_child_fields_and_associations_return_to_block_entry(self, order):
        old_items = list(order.items)
        first = old_items[0]
        added_before = dict(order._temp_cache["items"].added)

        with pytest.raises(ValidationError):
            with atomic_change(order):
                first.quantity = 3
                order.add_items(OrderItem(quantity=1, price=1.0))
                order.remove_items(old_items[1])
                order.total = 25.0

        assert order.items == old_items
        assert first.quantity == 2
        assert first.state_.is_changed is False
        assert order.total == 20.0
        assert order._temp_cache["items"].added == added_before
        assert order._temp_cache["items"].removed == {}
        assert order.state_.is_changed is False

    def test_children_linked_in_the_block_are_unlinked(self, order):
        new_item = OrderItem(quantity=1, price=1.0)
        new_note = OrderNote(text="Ring twice")

        with pytest.raises(ValidationError):
            with atomic_change(order):
                order.add_items(new_item)
                order.note = new_note
                order.total = -1.0

        for child in (new_item, new_note):
            assert child._root is None
            assert child._owner is None
            assert child.order_id is None
            assert child.state_.is_changed is False

    def test_events_raised_in_the_block_are_discarded(self, account):
        with pytest.raises(ValidationError):
            with atomic_change(account):
                account.name = "Renamed"
                account.raise_(AccountRenamed(name="Renamed"))
                account.balance = -5.0

        assert account.name == "Main"
        assert account._events == []

    def test_error_inside_the_block_keeps_its_changes(self, account):
        with pytest.raises(RuntimeError):
            with atomic_change(account):
                account.balance = 3.0
                raise RuntimeError("stop")

        assert account.balance == 3.0
        assert account.state_.is_changed is True

    def test_in_place_changes_to_list_and_dict_fields_are_undone(self):
        playlist = Playlist(tags=["rock"], settings={"shuffle": True})
        playlist.state_.mark_saved()

        with pytest.raises(ValidationError):
            with atomic_change(playlist):
                playlist.tags.append("banned")
                playlist.settings["shuffle"] = False

        assert playlist.tags == ["rock"]
        assert playlist.settings == {"shuffle": True}
        assert playlist.state_.is_changed is False

    def test_child_missing_from_the_cache_on_entry_is_restored(self, test_domain):
        repository = test_domain.repository_for(Order)
        stored = Order(total=5.0, items=[OrderItem(quantity=1, price=5.0)])
        repository.add(stored)
        order = repository.get(stored.id)
        # The block's entry checks walk every association, which loads the
        # children again before the entry snapshot is taken.
        order._state.fields_cache.pop("items")

        with pytest.raises(ValidationError):
            with atomic_change(order):
                item = order.items[0]
                item.quantity = 3

        assert item.quantity == 1
        assert item.state_.is_changed is False

    def test_passing_block_keeps_its_changes(self, order):
        with atomic_change(order):
            order.add_items(OrderItem(quantity=1, price=1.0))
            order.total = 21.0

        assert order.total == 21.0
        assert len(order.items) == 3
