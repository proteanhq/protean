"""Run the examples on ``docs/patterns/optimistic-concurrency-as-design-tool.md``."""

import threading

import pytest
from fastapi.testclient import TestClient

from protean import UnitOfWork
from protean.exceptions import ExpectedVersionError, ValidationError
from tests.docs.support import load_example

pytestmark = pytest.mark.no_test_domain


def commit_from_another_request(domain, write):
    """Run ``write`` to completion in a separate thread with its own context.

    The service under test is mid-transaction when this runs, so the write
    commits first and the service's own commit then hits a stale version.
    """
    errors = []

    def run():
        try:
            with domain.domain_context():
                write()
        except Exception as exc:  # surfaced in the calling test below
            errors.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    assert errors == []


def interleave_once(monkeypatch, aggregate_cls, method_name, domain, write):
    """Make the first call to ``method_name`` race against ``write``.

    Returns the list of calls, so a test can count the attempts.
    """
    original = getattr(aggregate_cls, method_name)
    calls = []

    def racing(self, *args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            commit_from_another_request(domain, write)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(aggregate_cls, method_name, racing)
    return calls


@pytest.fixture
def preferences():
    example = load_example("patterns/optimistic-concurrency-as-design-tool/001.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def seats():
    example = load_example("patterns/optimistic-concurrency-as-design-tool/002.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


@pytest.fixture
def carts():
    example = load_example("patterns/optimistic-concurrency-as-design-tool/003.py")
    example.domain.init(traverse=False)
    with example.domain.domain_context():
        yield example


class TestVersionConflict:
    def test_saving_a_stale_copy_raises_expected_version_error(self, preferences):
        repo = preferences.domain.repository_for(preferences.UserPreferences)
        repo.add(preferences.UserPreferences(user_id="u1"))

        first = repo.get("u1")
        stale = repo.get("u1")
        assert first._version == stale._version == 0

        first.update_theme("dark")
        repo.add(first)

        saved = repo.get("u1")
        assert saved._version == 1
        assert saved.theme == "dark"

        stale.update_theme("blue")
        with pytest.raises(ExpectedVersionError, match="Wrong expected version: 0"):
            repo.add(stale)

        after = repo.get("u1")
        assert after._version == 1
        assert after.theme == "dark"

    def test_second_customer_on_a_stale_seat_gets_a_conflict(self, seats):
        repo = seats.domain.repository_for(seats.SeatReservation)
        repo.add(
            seats.SeatReservation(
                reservation_id="E1-A1", event_id="E1", seat_number="A1"
            )
        )

        alice_copy = repo.get("E1-A1")
        bob_copy = repo.get("E1-A1")

        alice_copy.reserve("alice")
        repo.add(alice_copy)

        # Bob's copy still says "available", so the aggregate's own guard
        # passes. Only the version check stops the double booking.
        bob_copy.reserve("bob")
        with pytest.raises(ExpectedVersionError):
            repo.add(bob_copy)

        seat = repo.get("E1-A1")
        assert seat._version == 1
        assert seat.status == "reserved"
        assert seat.reserved_by == "alice"

    def test_reloading_after_a_cart_conflict_keeps_both_items(self, carts):
        repo = carts.domain.repository_for(carts.SharedCart)
        repo.add(carts.SharedCart(cart_id="c1", team_id="t1"))

        first = repo.get("c1")
        stale = repo.get("c1")

        first.add_item("apple", 1)
        repo.add(first)

        stale.add_item("pear", 2)
        with pytest.raises(ExpectedVersionError):
            repo.add(stale)

        # Reload the latest version, re-check, and apply the change again.
        latest = repo.get("c1")
        latest.add_item("pear", 2)
        repo.add(latest)

        cart = repo.get("c1")
        assert cart._version == 2
        assert {(i.product_id, i.quantity) for i in cart.items} == {
            ("apple", 1),
            ("pear", 2),
        }


class TestUserPreferences:
    def test_update_theme_raises_theme_updated(self, preferences):
        prefs = preferences.UserPreferences(user_id="u1")

        prefs.update_theme("dark")

        assert prefs.theme == "dark"
        [event] = prefs._events
        assert isinstance(event, preferences.ThemeUpdated)
        assert (event.user_id, event.theme) == ("u1", "dark")

    def test_toggle_notifications_raises_notifications_toggled(self, preferences):
        prefs = preferences.UserPreferences(user_id="u1")

        prefs.toggle_notifications(False)

        assert prefs.notifications_enabled is False
        [event] = prefs._events
        assert isinstance(event, preferences.NotificationsToggled)
        assert (event.user_id, event.enabled) == ("u1", False)

    def test_service_saves_the_new_theme(self, preferences):
        repo = preferences.domain.repository_for(preferences.UserPreferences)
        repo.add(preferences.UserPreferences(user_id="u1"))

        returned = preferences.PreferencesService().update_theme("u1", "dark")

        assert returned.theme == "dark"
        saved = repo.get("u1")
        assert saved.theme == "dark"
        assert saved._version == 1

    def test_service_retries_after_a_concurrent_change(self, preferences, monkeypatch):
        domain = preferences.domain
        repo = domain.repository_for(preferences.UserPreferences)
        repo.add(preferences.UserPreferences(user_id="u1"))

        def toggle_notifications():
            other = domain.repository_for(preferences.UserPreferences)
            prefs = other.get("u1")
            prefs.toggle_notifications(False)
            other.add(prefs)

        calls = interleave_once(
            monkeypatch,
            preferences.UserPreferences,
            "update_theme",
            domain,
            toggle_notifications,
        )

        preferences.PreferencesService().update_theme("u1", "dark")

        # The first attempt lost the race, the second one committed
        assert calls == [("dark",), ("dark",)]
        saved = repo.get("u1")
        assert (saved.theme, saved.notifications_enabled) == ("dark", False)
        assert saved._version == 2

    def test_inside_an_outer_unit_of_work_the_service_does_not_retry(
        self, preferences, monkeypatch
    ):
        domain = preferences.domain
        repo = domain.repository_for(preferences.UserPreferences)
        repo.add(preferences.UserPreferences(user_id="u1"))

        def toggle_notifications():
            other = domain.repository_for(preferences.UserPreferences)
            prefs = other.get("u1")
            prefs.toggle_notifications(False)
            other.add(prefs)

        calls = interleave_once(
            monkeypatch,
            preferences.UserPreferences,
            "update_theme",
            domain,
            toggle_notifications,
        )

        with pytest.raises(ExpectedVersionError):
            with UnitOfWork():
                preferences.PreferencesService().update_theme("u1", "dark")

        assert calls == [("dark",)]
        saved = repo.get("u1")
        assert (saved.theme, saved.notifications_enabled) == ("light", False)

    def test_service_gives_up_after_max_retries(self, preferences, monkeypatch):
        domain = preferences.domain
        repo = domain.repository_for(preferences.UserPreferences)
        repo.add(preferences.UserPreferences(user_id="u1"))
        original = preferences.UserPreferences.update_theme
        attempts = []

        def flip_sidebar():
            other = domain.repository_for(preferences.UserPreferences)
            prefs = other.get("u1")
            prefs.sidebar_collapsed = not prefs.sidebar_collapsed
            other.add(prefs)

        def always_loses(self, theme):
            attempts.append(theme)
            commit_from_another_request(domain, flip_sidebar)
            return original(self, theme)

        monkeypatch.setattr(preferences.UserPreferences, "update_theme", always_loses)

        with pytest.raises(ExpectedVersionError):
            preferences.PreferencesService().update_theme("u1", "dark")

        assert len(attempts) == preferences.MAX_RETRIES
        assert repo.get("u1").theme == "light"


class TestSeatReservation:
    def test_reserving_an_available_seat(self, seats):
        seat = seats.SeatReservation(
            reservation_id="E1-A1", event_id="E1", seat_number="A1"
        )

        seat.reserve("alice")

        assert seat.status == "reserved"
        assert seat.reserved_by == "alice"
        assert seat.reserved_at is not None
        [event] = seat._events
        assert isinstance(event, seats.SeatReserved)
        assert (
            event.reservation_id,
            event.event_id,
            event.seat_number,
            event.customer_id,
        ) == ("E1-A1", "E1", "A1", "alice")

    def test_handler_reserves_the_seat(self, seats):
        repo = seats.domain.repository_for(seats.SeatReservation)
        repo.add(
            seats.SeatReservation(
                reservation_id="E1-A1", event_id="E1", seat_number="A1"
            )
        )

        seats.domain.process(
            seats.ReserveSeat(reservation_id="E1-A1", customer_id="alice")
        )

        seat = repo.get("E1-A1")
        assert seat.status == "reserved"
        assert seat.reserved_by == "alice"

    def test_reserving_a_taken_seat_is_rejected(self, seats):
        repo = seats.domain.repository_for(seats.SeatReservation)
        repo.add(
            seats.SeatReservation(
                reservation_id="E1-A1", event_id="E1", seat_number="A1"
            )
        )
        seats.domain.process(
            seats.ReserveSeat(reservation_id="E1-A1", customer_id="alice")
        )

        with pytest.raises(seats.SeatAlreadyTaken) as exc:
            seats.domain.process(
                seats.ReserveSeat(reservation_id="E1-A1", customer_id="bob")
            )

        assert exc.value.seat_number == "A1"
        assert str(exc.value) == "Seat A1 was just reserved by another customer"
        seat = repo.get("E1-A1")
        assert seat.reserved_by == "alice"
        assert seat._version == 1

    def _race_bob_ahead_of_alice(self, seats, monkeypatch):
        repo = seats.domain.repository_for(seats.SeatReservation)
        repo.add(
            seats.SeatReservation(
                reservation_id="E1-A1", event_id="E1", seat_number="A1"
            )
        )
        return interleave_once(
            monkeypatch,
            seats.SeatReservation,
            "reserve",
            seats.domain,
            lambda: seats.domain.process(
                seats.ReserveSeat(reservation_id="E1-A1", customer_id="bob")
            ),
        )

    def test_a_concurrent_reservation_reaches_the_caller_as_seat_already_taken(
        self, seats, monkeypatch
    ):
        calls = self._race_bob_ahead_of_alice(seats, monkeypatch)

        with pytest.raises(seats.SeatAlreadyTaken) as exc:
            seats.domain.process(
                seats.ReserveSeat(reservation_id="E1-A1", customer_id="alice")
            )

        # Alice's first attempt lost at commit; the framework reran the
        # handler, and the reload saw Bob's reservation.
        assert calls == [("alice",), ("bob",), ("alice",)]
        assert exc.value.seat_number == "A1"
        seat = seats.domain.repository_for(seats.SeatReservation).get("E1-A1")
        assert seat.reserved_by == "bob"
        assert seat._version == 1

    def test_without_auto_retry_the_caller_gets_the_raw_conflict(
        self, seats, monkeypatch
    ):
        monkeypatch.setitem(
            seats.domain.config, "server", {"version_retry": {"enabled": False}}
        )
        calls = self._race_bob_ahead_of_alice(seats, monkeypatch)

        with pytest.raises(ExpectedVersionError):
            seats.domain.process(
                seats.ReserveSeat(reservation_id="E1-A1", customer_id="alice")
            )

        assert calls == [("alice",), ("bob",)]
        seat = seats.domain.repository_for(seats.SeatReservation).get("E1-A1")
        assert seat.reserved_by == "bob"


class TestSeatReservationApi:
    def _seat(self, seats):
        seats.domain.repository_for(seats.SeatReservation).add(
            seats.SeatReservation(
                reservation_id="E1-A1", event_id="E1", seat_number="A1"
            )
        )

    def test_reserving_a_free_seat_returns_reserved(self, seats):
        self._seat(seats)
        client = TestClient(seats.app)

        response = client.post(
            "/events/E1/seats/A1/reserve", params={"customer_id": "alice"}
        )

        assert response.status_code == 200
        assert response.json() == {"status": "reserved"}
        seat = seats.domain.repository_for(seats.SeatReservation).get("E1-A1")
        assert seat.reserved_by == "alice"

    def test_reserving_a_taken_seat_returns_409_with_a_suggestion(self, seats):
        self._seat(seats)
        client = TestClient(seats.app)
        client.post("/events/E1/seats/A1/reserve", params={"customer_id": "alice"})

        response = client.post(
            "/events/E1/seats/A1/reserve", params={"customer_id": "bob"}
        )

        assert response.status_code == 409
        assert response.json() == {
            "error": "Seat A1 was just reserved by another customer",
            "suggestion": "Please choose a different seat.",
        }
        seat = seats.domain.repository_for(seats.SeatReservation).get("E1-A1")
        assert seat.reserved_by == "alice"


class TestSharedCart:
    def test_adding_a_new_product_adds_a_line(self, carts):
        cart = carts.SharedCart(cart_id="c1", team_id="t1")

        cart.add_item("apple", 2)

        assert [(i.product_id, i.quantity) for i in cart.items] == [("apple", 2)]
        [event] = cart._events
        assert isinstance(event, carts.CartItemAdded)
        assert (event.cart_id, event.product_id, event.quantity) == ("c1", "apple", 2)

    def test_adding_the_same_product_merges_the_quantity(self, carts):
        cart = carts.SharedCart(cart_id="c1", team_id="t1")
        cart.add_item("apple", 2)

        cart.add_item("apple", 3)

        assert [(i.product_id, i.quantity) for i in cart.items] == [("apple", 5)]
        event = cart._events[-1]
        assert isinstance(event, carts.CartItemUpdated)
        assert (event.cart_id, event.product_id, event.new_quantity) == (
            "c1",
            "apple",
            5,
        )

    def test_aggregate_rejects_an_item_past_the_limit(self, carts):
        cart = carts.SharedCart(cart_id="c1", team_id="t1", max_items=1)
        cart.add_item("apple", 1)

        with pytest.raises(ValidationError) as exc:
            cart.add_item("pear", 1)

        assert exc.value.messages == {"items": ["Cart cannot exceed 1 items"]}
        assert [i.product_id for i in cart.items] == ["apple"]

    def test_aggregate_merges_the_same_product_into_a_full_cart(self, carts):
        cart = carts.SharedCart(cart_id="c1", team_id="t1", max_items=1)
        cart.add_item("apple", 1)

        cart.add_item("apple", 2)

        assert [(i.product_id, i.quantity) for i in cart.items] == [("apple", 3)]

    def test_service_adds_and_saves_the_item(self, carts):
        repo = carts.domain.repository_for(carts.SharedCart)
        repo.add(carts.SharedCart(cart_id="c1", team_id="t1"))

        carts.SharedCartService().add_item("c1", "apple", 2)
        carts.SharedCartService().add_item("c1", "apple", 1)

        cart = repo.get("c1")
        assert [(i.product_id, i.quantity) for i in cart.items] == [("apple", 3)]
        assert cart._version == 2

    def test_service_rejects_a_full_cart(self, carts):
        repo = carts.domain.repository_for(carts.SharedCart)
        cart = carts.SharedCart(cart_id="c1", team_id="t1", max_items=1)
        cart.add_item("apple", 1)
        repo.add(cart)

        with pytest.raises(ValidationError) as exc:
            carts.SharedCartService().add_item("c1", "pear", 1)

        assert exc.value.messages == {"items": ["Cart is full. Remove items first."]}
        assert [i.product_id for i in repo.get("c1").items] == ["apple"]

    def test_service_merges_the_same_product_into_a_full_cart(self, carts):
        repo = carts.domain.repository_for(carts.SharedCart)
        cart = carts.SharedCart(cart_id="c1", team_id="t1", max_items=1)
        cart.add_item("apple", 1)
        repo.add(cart)

        carts.SharedCartService().add_item("c1", "apple", 2)

        cart = repo.get("c1")
        assert [(i.product_id, i.quantity) for i in cart.items] == [("apple", 3)]

    def test_service_merges_a_concurrent_add(self, carts, monkeypatch):
        domain = carts.domain
        repo = domain.repository_for(carts.SharedCart)
        repo.add(carts.SharedCart(cart_id="c1", team_id="t1"))
        add_item = carts.SharedCart.add_item

        def teammate_adds_apples():
            other = domain.repository_for(carts.SharedCart)
            cart = other.get("c1")
            add_item(cart, "apple", 2)
            other.add(cart)

        calls = interleave_once(
            monkeypatch, carts.SharedCart, "add_item", domain, teammate_adds_apples
        )

        carts.SharedCartService().add_item("c1", "pear", 1)

        assert calls == [("pear", 1), ("pear", 1)]
        cart = repo.get("c1")
        assert sorted((i.product_id, i.quantity) for i in cart.items) == [
            ("apple", 2),
            ("pear", 1),
        ]

    def test_service_rechecks_the_limit_after_a_conflict(self, carts, monkeypatch):
        domain = carts.domain
        repo = domain.repository_for(carts.SharedCart)
        repo.add(carts.SharedCart(cart_id="c1", team_id="t1", max_items=1))
        add_item = carts.SharedCart.add_item

        def teammate_fills_the_cart():
            other = domain.repository_for(carts.SharedCart)
            cart = other.get("c1")
            add_item(cart, "apple", 1)
            other.add(cart)

        interleave_once(
            monkeypatch, carts.SharedCart, "add_item", domain, teammate_fills_the_cart
        )

        # The first attempt saw an empty cart. The reload sees it full.
        with pytest.raises(ValidationError) as exc:
            carts.SharedCartService().add_item("c1", "pear", 1)

        assert exc.value.messages == {"items": ["Cart is full. Remove items first."]}
        assert [i.product_id for i in repo.get("c1").items] == ["apple"]
