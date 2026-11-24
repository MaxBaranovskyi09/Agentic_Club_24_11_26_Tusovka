import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from pathlib import Path

from accounts.models import User
from events.models import Comment, Event, PrivateAccess, Registration
from tests.conftest import image_bytes, make_event, make_user

pytestmark = pytest.mark.django_db


def test_email_saved_lowercase_and_unique_case_insensitive():
    user = make_user("  MiXeD@Example.COM ")
    assert user.email == "mixed@example.com"
    with pytest.raises(IntegrityError), transaction.atomic():
        make_user("MIXED@example.com")


def test_get_by_natural_key_case_insensitive():
    user = make_user("me@example.com")
    assert User.objects.get_by_natural_key("ME@EXAMPLE.COM") == user


def test_create_superuser():
    admin = User.objects.create_superuser(email="Admin@Example.com", password="x-Strong-12345", name="Адмін")
    assert admin.is_staff and admin.is_superuser
    assert admin.email == "admin@example.com"
    with pytest.raises(ValueError):
        User.objects.create_superuser(email="a2@example.com", password="x", name="A", is_staff=False)
    with pytest.raises(ValueError):
        User.objects.create_user(email="", password="x", name="A")


def test_user_has_no_username_and_str_is_name():
    user = make_user("me@example.com", "Марта")
    assert not hasattr(user, "username") or user.username is None
    assert str(user) == "Марта"
    assert user.get_full_name() == "Марта"


def test_user_name_validation():
    user = User(email="x@example.com", name="   ")
    with pytest.raises(ValidationError):
        user.full_clean()
    user = User(email="x@example.com", name="я" * 51)
    with pytest.raises(ValidationError):
        user.full_clean()


def test_event_defaults(author):
    a = make_event(author)
    b = make_event(author)
    assert a.public_id != b.public_id
    assert a.invite_token != b.invite_token
    assert len(a.invite_token) >= 43  # token_urlsafe(32)


def test_regenerate_invite_token(author):
    event = make_event(author)
    old = event.invite_token
    event.regenerate_invite_token()
    event.refresh_from_db()
    assert event.invite_token != old


@pytest.mark.parametrize("capacity", [0, 10001])
def test_capacity_db_constraint(author, capacity):
    with pytest.raises(IntegrityError), transaction.atomic():
        make_event(author, capacity=capacity)


def test_event_model_validation(author):
    event = Event(author=author, title="  ", description="", starts_at=make_event(author).starts_at, capacity=5)
    with pytest.raises(ValidationError):
        event.full_clean()


def test_registration_unique_at_db_level(event, other):
    Registration.objects.create(event=event, user=other)
    with pytest.raises(IntegrityError), transaction.atomic():
        Registration.objects.create(event=event, user=other)


def test_private_access_unique_at_db_level(private_event, other):
    PrivateAccess.objects.create(event=private_event, user=other)
    with pytest.raises(IntegrityError), transaction.atomic():
        PrivateAccess.objects.create(event=private_event, user=other)


def test_delete_event_cascades(event, other):
    Registration.objects.create(event=event, user=other)
    Comment.objects.create(event=event, author=other, text="hi")
    PrivateAccess.objects.create(event=event, user=other)
    event.delete()
    assert not Registration.objects.exists()
    assert not Comment.objects.exists()
    assert not PrivateAccess.objects.exists()


def test_delete_user_cascades_and_removes_cover_files(author, other, settings, django_capture_on_commit_callbacks):
    event = make_event(author)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    path = Path(settings.MEDIA_ROOT) / event.cover.name
    assert path.exists()
    theirs = make_event(other)
    Registration.objects.create(event=theirs, user=author)
    Comment.objects.create(event=theirs, author=author, text="hi")
    with django_capture_on_commit_callbacks(execute=True):
        author.delete()
    assert not Event.objects.filter(author_id=author.pk).exists()
    assert not Registration.objects.exists()
    assert not Comment.objects.exists()
    assert Event.objects.filter(pk=theirs.pk).exists()
    assert not path.exists()


def test_regenerate_token_does_not_touch_cover_file(author, settings, django_capture_on_commit_callbacks):
    event = make_event(author)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    path = Path(settings.MEDIA_ROOT) / event.cover.name
    with django_capture_on_commit_callbacks(execute=True):
        event.regenerate_invite_token()
    assert path.exists()


def test_cover_upload_path_generated(author):
    from events.models import cover_upload_to

    assert cover_upload_to(None, "../../etc/passwd").startswith("covers/")
    assert cover_upload_to(None, "../../etc/passwd").endswith(".bin")
    assert cover_upload_to(None, "a.PNG").endswith(".png")
    assert cover_upload_to(None, "a.png") != cover_upload_to(None, "a.png")
