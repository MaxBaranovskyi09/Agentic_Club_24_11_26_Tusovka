import pytest
from django.urls import reverse

from accounts.models import User
from tests.conftest import PASSWORD, make_user

pytestmark = pytest.mark.django_db


def test_signup_creates_user_with_lowercase_email(client):
    resp = client.post(
        reverse("accounts:signup"),
        {"email": "New.User@Example.COM", "name": "  Оля  ", "password1": PASSWORD, "password2": PASSWORD},
    )
    assert resp.status_code == 302
    user = User.objects.get()
    assert user.email == "new.user@example.com"
    assert user.name == "Оля"


def test_signup_rejects_blank_name_and_duplicate_email(client):
    make_user("taken@example.com")
    resp = client.post(
        reverse("accounts:signup"),
        {"email": "TAKEN@example.com", "name": "   ", "password1": PASSWORD, "password2": PASSWORD},
    )
    assert resp.status_code == 200
    assert User.objects.count() == 1


def test_signup_weak_password_rejected(client):
    resp = client.post(
        reverse("accounts:signup"),
        {"email": "a@example.com", "name": "A", "password1": "123", "password2": "123"},
    )
    assert resp.status_code == 200
    assert not User.objects.exists()


def test_login_case_insensitive_email(client):
    make_user("me@example.com")
    resp = client.post(reverse("accounts:login"), {"username": "ME@Example.com", "password": PASSWORD})
    assert resp.status_code == 302
    assert "_auth_user_id" in client.session


def test_login_error_is_generic(client):
    make_user("me@example.com")
    wrong_pw = client.post(reverse("accounts:login"), {"username": "me@example.com", "password": "nope"})
    no_user = client.post(reverse("accounts:login"), {"username": "ghost@example.com", "password": "nope"})
    for resp in (wrong_pw, no_user):
        assert resp.status_code == 200
        assert "Невірний email або пароль" in resp.content.decode()


def test_login_rate_limited_after_5_failures(client):
    make_user("me@example.com")
    url = reverse("accounts:login")
    for _ in range(5):
        client.post(url, {"username": "me@example.com", "password": "wrong"})
    # Навіть правильний пароль блокується, поки діє ліміт.
    resp = client.post(url, {"username": "me@example.com", "password": PASSWORD})
    assert resp.status_code == 200
    assert "Забагато" in resp.content.decode()
    assert "_auth_user_id" not in client.session


def test_signup_rate_limited(client, settings):
    settings.SIGNUP_RATE_LIMIT = (2, 3600)
    url = reverse("accounts:signup")
    for i in range(2):
        client.post(url, {"email": f"u{i}@example.com", "name": "U", "password1": PASSWORD, "password2": PASSWORD})
        client.logout()
    resp = client.post(url, {"email": "u9@example.com", "name": "U", "password1": PASSWORD, "password2": PASSWORD})
    assert resp.status_code == 429
    assert User.objects.count() == 2


def test_logout_get_not_allowed(client):
    user = make_user("me@example.com")
    client.force_login(user)
    resp = client.get(reverse("accounts:logout"))
    assert resp.status_code == 405
    assert "_auth_user_id" in client.session
    resp = client.post(reverse("accounts:logout"))
    assert resp.status_code == 302
    assert "_auth_user_id" not in client.session


def test_login_next_redirect_is_safe(client):
    make_user("me@example.com")
    resp = client.post(
        reverse("accounts:login") + "?next=https://evil.example.com/",
        {"username": "me@example.com", "password": PASSWORD, "next": "https://evil.example.com/"},
    )
    assert resp.status_code == 302
    assert "evil" not in resp["Location"]
