"""Справжні паралельні запити (потоки + окремі зʼєднання з PostgreSQL)."""

import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from events import services
from events.models import Event, PrivateAccess, Registration
from tests.conftest import make_event, make_user

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(autouse=True)
def _postgres_only():
    if connection.vendor != "postgresql":
        pytest.skip("Потрібен PostgreSQL")


def run_parallel(funcs):
    barrier = threading.Barrier(len(funcs))
    errors = []

    def wrap(fn):
        try:
            barrier.wait()
            fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=wrap, args=(f,)) for f in funcs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return errors


def _register(user, event):
    def fn():
        try:
            services.register(user, event.public_id)
        except services.RegistrationError:
            pass
    return fn


@pytest.mark.parametrize("capacity,users", [(1, 10), (5, 20), (10, 10)])
def test_parallel_registration_never_exceeds_capacity(capacity, users):
    author = make_user("a@example.com")
    event = make_event(author, capacity=capacity)
    people = [make_user(f"p{i}@example.com") for i in range(users)]
    errors = run_parallel([_register(u, event) for u in people])
    assert errors == []
    assert Registration.objects.filter(event=event).count() == min(capacity, users)


def test_parallel_capacity_decrease_vs_registrations():
    author = make_user("a@example.com")
    event = make_event(author, capacity=10)
    for i in range(3):
        Registration.objects.create(event=event, user=make_user(f"pre{i}@example.com"))
    newcomers = [make_user(f"n{i}@example.com") for i in range(6)]

    def shrink():
        c = Client()
        c.force_login(author)
        c.post(
            reverse("events:edit", args=[event.public_id]),
            {
                "title": event.title,
                "description": "",
                "starts_at": timezone.localtime(timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M"),
                "capacity": "4",
            },
        )

    errors = run_parallel([shrink] + [_register(u, event) for u in newcomers])
    assert errors == []
    event.refresh_from_db()
    count = Registration.objects.filter(event=event).count()
    # Інваріант: записаних ніколи не більше, ніж місць.
    assert count <= event.capacity
    assert event.capacity in (4, 10)


def test_parallel_cancel_and_register_on_full_event():
    author = make_user("a@example.com")
    event = make_event(author, capacity=1)
    holder = make_user("holder@example.com")
    Registration.objects.create(event=event, user=holder)
    others = [make_user(f"o{i}@example.com") for i in range(5)]

    def cancel():
        try:
            services.unregister(holder, event.public_id)
        except services.RegistrationError:
            pass

    errors = run_parallel([cancel] + [_register(u, event) for u in others])
    assert errors == []
    assert Registration.objects.filter(event=event).count() <= 1


def test_parallel_invite_open_same_user():
    author = make_user("a@example.com")
    guest = make_user("g@example.com")
    event = make_event(author, is_private=True)
    url = reverse("events:invite", args=[event.invite_token])
    statuses = []

    def open_invite():
        c = Client()
        c.force_login(guest)
        statuses.append(c.get(url).status_code)

    errors = run_parallel([open_invite for _ in range(6)])
    assert errors == []
    assert set(statuses) == {302}
    assert PrivateAccess.objects.filter(user=guest, event=event).count() == 1


def test_parallel_http_registration_same_user_no_500():
    author = make_user("a@example.com")
    user = make_user("u@example.com")
    event = make_event(author, capacity=5)
    url = reverse("events:register", args=[event.public_id])
    statuses = []

    def go():
        c = Client(raise_request_exception=False)
        c.force_login(user)
        statuses.append(c.post(url).status_code)

    errors = run_parallel([go for _ in range(6)])
    assert errors == []
    assert set(statuses) == {302}
    assert Registration.objects.filter(event=event, user=user).count() == 1


def test_parallel_delete_and_register():
    author = make_user("a@example.com")
    event = make_event(author, capacity=5)
    people = [make_user(f"p{i}@example.com") for i in range(4)]

    def delete():
        c = Client()
        c.force_login(author)
        c.post(reverse("events:delete", args=[event.public_id]))

    def reg(u):
        def fn():
            c = Client(raise_request_exception=False)
            c.force_login(u)
            resp = c.post(reverse("events:register", args=[event.public_id]))
            assert resp.status_code in (302, 404)
        return fn

    errors = run_parallel([delete] + [reg(u) for u in people])
    assert errors == []
    assert not Event.objects.filter(pk=event.pk).exists()
    assert not Registration.objects.exists()


def test_parallel_delete_and_comment():
    author = make_user("a@example.com")
    event = make_event(author)
    people = [make_user(f"c{i}@example.com") for i in range(4)]

    def delete():
        c = Client()
        c.force_login(author)
        c.post(reverse("events:delete", args=[event.public_id]))

    def comment(u):
        def fn():
            c = Client(raise_request_exception=False)
            c.force_login(u)
            resp = c.post(reverse("events:comment_add", args=[event.public_id]), {"text": "hi"})
            assert resp.status_code in (302, 404), resp.status_code
        return fn

    errors = run_parallel([delete] + [comment(u) for u in people])
    assert errors == []
    assert not Event.objects.filter(pk=event.pk).exists()
