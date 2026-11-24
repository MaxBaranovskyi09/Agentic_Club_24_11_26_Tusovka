from types import SimpleNamespace

import pytest
from django.test import Client, RequestFactory
from django.urls import reverse

from accounts import ratelimit
from config import views as error_views
from events.models import Comment, Event, Registration
from tests.conftest import PASSWORD, event_post_data, make_event, make_user

pytestmark = pytest.mark.django_db


# --- CSRF: POST без токена відхиляється ---

@pytest.fixture
def csrf_client(other):
    c = Client(enforce_csrf_checks=True)
    c.force_login(other)
    return c


@pytest.mark.parametrize(
    "name,data",
    [
        ("events:register", {}),
        ("events:unregister", {}),
        ("events:comment_add", {"text": "x"}),
    ],
)
def test_csrf_required_on_event_actions(csrf_client, event, name, data):
    resp = csrf_client.post(reverse(name, args=[event.public_id]), data)
    assert resp.status_code == 403
    assert not Registration.objects.exists()
    assert not Comment.objects.exists()


def test_csrf_required_on_create(csrf_client):
    resp = csrf_client.post(reverse("events:create"), event_post_data())
    assert resp.status_code == 403
    assert not Event.objects.exists()


def test_csrf_required_on_delete_and_logout(author):
    c = Client(enforce_csrf_checks=True)
    c.force_login(author)
    event = make_event(author)
    assert c.post(reverse("events:delete", args=[event.public_id])).status_code == 403
    assert Event.objects.filter(pk=event.pk).exists()
    assert c.post(reverse("accounts:logout")).status_code == 403
    assert "_auth_user_id" in c.session


def test_csrf_required_on_login():
    make_user("me@example.com")
    c = Client(enforce_csrf_checks=True)
    resp = c.post(reverse("accounts:login"), {"username": "me@example.com", "password": PASSWORD})
    assert resp.status_code == 403


# --- Заголовки та cookie ---

def test_security_headers(client):
    resp = client.get(reverse("events:home"))
    assert resp["X-Frame-Options"] == "DENY"
    assert resp["X-Content-Type-Options"] == "nosniff"
    assert resp["Referrer-Policy"] == "same-origin"


def test_session_cookie_httponly(client, settings):
    make_user("me@example.com")
    client.post(reverse("accounts:login"), {"username": "me@example.com", "password": PASSWORD})
    assert client.cookies[settings.SESSION_COOKIE_NAME]["httponly"]


def _load_settings(monkeypatch, debug_value):
    """Перечитати config/settings.py з заданим DEBUG, не чіпаючи .env розробника."""
    import importlib

    import environ

    import config.settings as mod

    monkeypatch.setattr(environ.Env, "read_env", staticmethod(lambda *a, **kw: None))
    if debug_value is None:
        monkeypatch.delenv("DEBUG", raising=False)
    else:
        monkeypatch.setenv("DEBUG", debug_value)
    monkeypatch.setenv("SECRET_KEY", "test")
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@localhost/db")
    try:
        reloaded = importlib.reload(mod)
        return SimpleNamespace(**{k: getattr(reloaded, k) for k in dir(reloaded) if k.isupper()})
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_prod_settings_when_debug_false(monkeypatch):
    s = _load_settings(monkeypatch, "False")
    assert s.DEBUG is False
    assert s.SESSION_COOKIE_SECURE is True
    assert s.CSRF_COOKIE_SECURE is True
    assert s.SESSION_COOKIE_HTTPONLY is True
    assert s.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert s.X_FRAME_OPTIONS == "DENY"
    assert s.SECURE_CONTENT_TYPE_NOSNIFF is True


def test_debug_defaults_to_false_when_unset(monkeypatch):
    s = _load_settings(monkeypatch, None)
    assert s.DEBUG is False
    assert s.SESSION_COOKIE_SECURE is True


def test_debug_true_relaxes_cookie_secure(monkeypatch):
    s = _load_settings(monkeypatch, "True")
    assert s.DEBUG is True
    assert s.SESSION_COOKIE_SECURE is False


def test_debug_off_in_tests(settings):
    assert settings.DEBUG is False


# --- Сторінки помилок ---

def test_error_handlers_render_custom_pages():
    rf = RequestFactory()
    request = rf.get("/")
    from django.contrib.auth.models import AnonymousUser

    request.user = AnonymousUser()
    resp = error_views.server_error(request)
    assert resp.status_code == 500
    body = resp.content.decode()
    assert "Щось пішло не так" in body
    assert "Traceback" not in body
    resp = error_views.permission_denied(request)
    assert resp.status_code == 403 and "Доступ заборонено" in resp.content.decode()
    resp = error_views.bad_request(request)
    assert resp.status_code == 400


def test_403_page_custom(other_client, event):
    resp = other_client.get(reverse("events:edit", args=[event.public_id]))
    assert resp.status_code == 403
    assert "Доступ заборонено" in resp.content.decode()


def test_unhandled_exception_returns_custom_500(client, monkeypatch):
    from events import views

    def boom(*a, **kw):
        raise RuntimeError("secret internals")

    monkeypatch.setattr(views, "render", boom)
    c = Client(raise_request_exception=False)
    resp = c.get(reverse("events:home"))
    assert resp.status_code == 500
    assert "secret internals" not in resp.content.decode()
    assert "Щось пішло не так" in resp.content.decode()


# --- XSS у різних місцях ---

XSS = "<script>alert(1)</script>"


def test_xss_in_search_query_escaped(client):
    html = client.get(reverse("events:home"), {"q": XSS}).content.decode()
    assert XSS not in html
    assert "&lt;script&gt;" in html


def test_xss_in_user_name_in_participants_and_header(client, author, event):
    evil = make_user("evil@example.com", XSS)
    Registration.objects.create(event=event, user=evil)
    client.force_login(author)
    html = client.get(reverse("events:detail", args=[event.public_id])).content.decode()
    assert XSS not in html
    client.force_login(evil)
    html = client.get(reverse("events:profile")).content.decode()
    assert XSS not in html


def test_featured_event_xss_escaped(client, author):
    make_event(author, title=XSS)
    html = client.get(reverse("events:home")).content.decode()
    assert XSS not in html


# --- Rate limit / IP ---

def test_client_ip_ignores_xff_by_default(rf, settings):
    settings.USE_X_FORWARDED_FOR = False
    req = rf.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6", REMOTE_ADDR="10.0.0.1")
    assert ratelimit.client_ip(req) == "10.0.0.1"


def test_client_ip_uses_last_xff_hop_when_enabled(rf, settings):
    settings.USE_X_FORWARDED_FOR = True
    req = rf.get("/", HTTP_X_FORWARDED_FOR="6.6.6.6, 1.2.3.4", REMOTE_ADDR="10.0.0.1")
    assert ratelimit.client_ip(req) == "1.2.3.4"
    req = rf.get("/", REMOTE_ADDR="10.0.0.1")
    assert ratelimit.client_ip(req) == "10.0.0.1"


def test_login_limit_is_per_ip(client):
    make_user("me@example.com")
    url = reverse("accounts:login")
    for _ in range(5):
        client.post(url, {"username": "me@example.com", "password": "bad"}, REMOTE_ADDR="1.1.1.1")
    blocked = client.post(url, {"username": "me@example.com", "password": PASSWORD}, REMOTE_ADDR="1.1.1.1")
    assert "_auth_user_id" not in client.session
    assert "Забагато" in blocked.content.decode()
    ok = client.post(url, {"username": "me@example.com", "password": PASSWORD}, REMOTE_ADDR="2.2.2.2")
    assert ok.status_code == 302


def test_login_limit_case_insensitive_email(client):
    make_user("me@example.com")
    url = reverse("accounts:login")
    for i in range(5):
        email = "ME@example.com" if i % 2 else "me@EXAMPLE.com"
        client.post(url, {"username": email, "password": "bad"})
    resp = client.post(url, {"username": "me@example.com", "password": PASSWORD})
    assert "_auth_user_id" not in client.session
    assert "Забагато" in resp.content.decode()


def test_successful_login_resets_counter(client):
    make_user("me@example.com")
    url = reverse("accounts:login")
    for _ in range(4):
        client.post(url, {"username": "me@example.com", "password": "bad"})
    client.post(url, {"username": "me@example.com", "password": PASSWORD})
    client.logout()
    for _ in range(4):
        client.post(url, {"username": "me@example.com", "password": "bad"})
    resp = client.post(url, {"username": "me@example.com", "password": PASSWORD})
    assert resp.status_code == 302


def test_four_failures_still_allow_login(client):
    make_user("me@example.com")
    url = reverse("accounts:login")
    for _ in range(4):
        client.post(url, {"username": "me@example.com", "password": "bad"})
    assert client.post(url, {"username": "me@example.com", "password": PASSWORD}).status_code == 302


def test_comment_rate_limit_is_per_user(client, event, other, author):
    url = reverse("events:comment_add", args=[event.public_id])
    client.force_login(other)
    client.post(url, {"text": "1"})
    client.force_login(author)
    client.post(url, {"text": "2"})
    assert Comment.objects.count() == 2


def test_comment_allowed_again_after_window(other_client, event):
    from django.core.cache import cache

    url = reverse("events:comment_add", args=[event.public_id])
    other_client.post(url, {"text": "1"})
    cache.clear()  # імітуємо, що 5 секунд минуло
    other_client.post(url, {"text": "2"})
    assert Comment.objects.count() == 2


def test_rejected_comment_does_not_consume_rate_limit(other_client, event):
    url = reverse("events:comment_add", args=[event.public_id])
    other_client.post(url, {"text": "   "})
    other_client.post(url, {"text": "ok"})
    assert Comment.objects.count() == 1


# --- Обмеження розміру запиту ---

def test_invalid_content_length_does_not_crash(client):
    resp = client.get(reverse("events:home"), CONTENT_LENGTH="abc")
    assert resp.status_code == 200


def test_large_body_rejected_before_view(other_client, event, settings):
    settings.REQUEST_BODY_MAX_BYTES = 100
    resp = other_client.post(
        reverse("events:comment_add", args=[event.public_id]), {"text": "x" * 500}
    )
    assert resp.status_code == 413
    assert not Comment.objects.exists()


# --- Медіа не доступні як статика ---

def test_static_does_not_expose_source_or_env(client):
    for path in ("/static/../.env", "/.env", "/static/.env", "/media/"):
        assert client.get(path).status_code == 404


# --- Запуск з чистого клону ---

def test_pages_work_with_debug_false_without_collectstatic(client, settings, tmp_path):
    """Регресія: CompressedManifestStaticFilesStorage без collectstatic давав 500 на всіх сторінках."""
    settings.STATIC_ROOT = tmp_path / "empty_static"
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "config.storage.ForgivingManifestStaticFilesStorage"},
    }
    for url in (reverse("events:home"), reverse("accounts:login"), reverse("accounts:signup"), "/nope/"):
        resp = client.get(url)
        assert resp.status_code in (200, 404), url
        assert "/static/css/style.css" in resp.content.decode()


def test_allowed_hosts_defaults(monkeypatch):
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    s = _load_settings(monkeypatch, "True")
    assert s.ALLOWED_HOSTS == ["*"]
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    s = _load_settings(monkeypatch, "False")
    assert "*" not in s.ALLOWED_HOSTS
    assert "127.0.0.1" in s.ALLOWED_HOSTS


def test_explicit_allowed_hosts_respected(monkeypatch):
    monkeypatch.setenv("ALLOWED_HOSTS", ".up.railway.app")
    s = _load_settings(monkeypatch, "False")
    assert s.ALLOWED_HOSTS == [".up.railway.app"]


def test_secure_cookies_override(monkeypatch):
    monkeypatch.setenv("SECURE_COOKIES", "False")
    s = _load_settings(monkeypatch, "False")
    assert s.SESSION_COOKIE_SECURE is False and s.CSRF_COOKIE_SECURE is False
    monkeypatch.delenv("SECURE_COOKIES", raising=False)
    s = _load_settings(monkeypatch, "False")
    assert s.SESSION_COOKIE_SECURE is True
