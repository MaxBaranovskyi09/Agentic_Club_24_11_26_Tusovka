import io
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from PIL import Image

from accounts.models import User
from events.models import Event

PASSWORD = "Sup3r-Secret-pass!"


@pytest.fixture(autouse=True)
def _test_settings(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _clear_cache(db):
    cache.clear()
    yield
    cache.clear()


def make_user(email, name="Тест"):
    return User.objects.create_user(email=email, password=PASSWORD, name=name)


def make_event(author, **kwargs):
    data = {
        "title": "Подія",
        "description": "Опис",
        "starts_at": timezone.now() + timedelta(days=3),
        "capacity": 10,
        "is_private": False,
    }
    data.update(kwargs)
    return Event.objects.create(author=author, **data)


@pytest.fixture
def author(db):
    return make_user("author@example.com", "Автор")


@pytest.fixture
def other(db):
    return make_user("other@example.com", "Інший")


@pytest.fixture
def event(author):
    return make_event(author, title="Публічна подія")


@pytest.fixture
def private_event(author):
    return make_event(author, title="Секретна вечірка", is_private=True)


@pytest.fixture
def author_client(client, author):
    client.force_login(author)
    return client


@pytest.fixture
def other_client(client, other):
    client.force_login(other)
    return client


def image_bytes(fmt="PNG", size=(20, 20)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 80, 40)).save(buf, format=fmt)
    return buf.getvalue()


def event_post_data(**overrides):
    starts = timezone.localtime(timezone.now() + timedelta(days=5))
    data = {
        "title": "Нова подія",
        "description": "Опис події",
        "starts_at": starts.strftime("%Y-%m-%dT%H:%M"),
        "capacity": "10",
    }
    data.update(overrides)
    return data
