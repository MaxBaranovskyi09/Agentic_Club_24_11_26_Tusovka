import threading
from datetime import timedelta

import pytest
from django.db import connection
from django.urls import reverse
from django.utils import timezone

from events import services
from events.models import Registration
from tests.conftest import make_event, make_user

pytestmark = pytest.mark.django_db


def register_url(event):
    return reverse("events:register", args=[event.public_id])


def test_register_and_cancel(other_client, other, event):
    resp = other_client.post(register_url(event))
    assert resp.status_code == 302
    assert Registration.objects.filter(event=event, user=other).count() == 1
    resp = other_client.post(reverse("events:unregister", args=[event.public_id]))
    assert resp.status_code == 302
    assert not Registration.objects.filter(event=event, user=other).exists()


def test_register_via_get_does_nothing(other_client, event):
    resp = other_client.get(register_url(event))
    assert resp.status_code == 405
    assert not Registration.objects.exists()


def test_anonymous_cannot_register(client, event):
    resp = client.post(register_url(event))
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp["Location"]
    assert not Registration.objects.exists()


def test_no_duplicates(other_client, other, event):
    other_client.post(register_url(event))
    resp = other_client.post(register_url(event), follow=True)
    assert resp.status_code == 200
    assert "вже записані" in resp.content.decode()
    assert Registration.objects.filter(event=event, user=other).count() == 1


def test_author_cannot_register(author_client, event):
    resp = author_client.post(register_url(event), follow=True)
    assert "Автор не може" in resp.content.decode()
    assert not Registration.objects.exists()


def test_cannot_register_for_past_event(other_client, author):
    past = make_event(author, starts_at=timezone.now() - timedelta(minutes=1))
    resp = other_client.post(register_url(past), follow=True)
    assert "запис закрито" in resp.content.decode()
    assert not Registration.objects.exists()


def test_capacity_respected(client, author):
    event = make_event(author, capacity=2)
    for i in range(3):
        client.force_login(make_user(f"u{i}@example.com"))
        client.post(register_url(event))
    assert Registration.objects.filter(event=event).count() == 2


def test_cancel_only_own_registration(client, author, other, event):
    third = make_user("third@example.com")
    Registration.objects.create(event=event, user=third)
    client.force_login(other)
    client.post(reverse("events:unregister", args=[event.public_id]))
    assert Registration.objects.filter(event=event, user=third).exists()


def test_integrity_error_handled_as_already_registered(other, event, monkeypatch):
    """Навіть якщо перевірка exists() пропустила дубль, UniqueConstraint → дружня помилка, не 500."""
    Registration.objects.create(event=event, user=other)
    real_filter = Registration.objects.filter

    class FakeQS:
        def __init__(self, qs):
            self.qs = qs

        def exists(self):
            return False

        def count(self):
            return self.qs.count()

    def fake_filter(*args, **kwargs):
        qs = real_filter(*args, **kwargs)
        return FakeQS(qs) if "user" in kwargs else qs

    monkeypatch.setattr(Registration.objects, "filter", fake_filter)
    with pytest.raises(services.RegistrationError, match="вже записані"):
        services.register(other, event.public_id)


@pytest.mark.django_db(transaction=True)
def test_parallel_registrations_do_not_exceed_capacity():
    if connection.vendor != "postgresql":
        pytest.skip("Потрібен PostgreSQL для перевірки select_for_update")
    author = make_user("a@example.com")
    event = make_event(author, capacity=3)
    users = [make_user(f"p{i}@example.com") for i in range(12)]
    barrier = threading.Barrier(len(users))
    results = []

    def worker(user):
        try:
            barrier.wait()
            services.register(user, event.public_id)
            results.append("ok")
        except services.RegistrationError:
            results.append("full")
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(u,)) for u in users]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 3
    assert Registration.objects.filter(event=event).count() == 3


@pytest.mark.django_db(transaction=True)
def test_parallel_duplicate_registration_same_user():
    if connection.vendor != "postgresql":
        pytest.skip("Потрібен PostgreSQL")
    author = make_user("a@example.com")
    user = make_user("u@example.com")
    event = make_event(author, capacity=10)
    barrier = threading.Barrier(5)
    errors = []

    def worker():
        try:
            barrier.wait()
            services.register(user, event.public_id)
        except services.RegistrationError:
            pass
        except Exception as exc:  # будь-що інше = 500 у проді
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert Registration.objects.filter(event=event, user=user).count() == 1
