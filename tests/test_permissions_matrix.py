"""Повна матриця прав: хто × яка подія × яка дія. Перевіряє лише сервер — запити йдуть напряму."""

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import Http404
from django.urls import reverse

from events.models import Comment, Event, PrivateAccess, Registration
from events.permissions import can_edit, can_view, get_editable_event, get_viewable_event
from tests.conftest import event_post_data, image_bytes, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def guest(private_event):
    user = make_user("guest@example.com", "Гість")
    PrivateAccess.objects.create(user=user, event=private_event)
    return user


# --- Юніт-тести helper'ів ---

def test_can_view_public(event, author, other):
    assert can_view(AnonymousUser(), event)
    assert can_view(author, event)
    assert can_view(other, event)


def test_can_view_private(private_event, author, other, guest):
    assert not can_view(AnonymousUser(), private_event)
    assert not can_view(other, private_event)
    assert can_view(author, private_event)
    assert can_view(guest, private_event)


def test_can_edit_only_author(event, private_event, author, other, guest):
    for ev in (event, private_event):
        assert can_edit(author, ev)
        assert not can_edit(other, ev)
        assert not can_edit(guest, ev)
        assert not can_edit(AnonymousUser(), ev)


def test_access_to_one_private_event_does_not_open_another(author, guest, private_event):
    from tests.conftest import make_event

    second = make_event(author, title="Інша приватна", is_private=True)
    assert not can_view(guest, second)


def test_get_editable_event_errors(event, private_event, other, guest):
    with pytest.raises(PermissionDenied):
        get_editable_event(other, event.public_id)
    with pytest.raises(Http404):
        get_editable_event(other, private_event.public_id)
    # Навіть з PrivateAccess редагувати не можна, і відповідь — 404 (приватна).
    with pytest.raises(Http404):
        get_editable_event(guest, private_event.public_id)


def test_get_viewable_event_unknown_uuid(other):
    import uuid

    with pytest.raises(Http404):
        get_viewable_event(other, uuid.uuid4())


def test_inactive_user_session_is_not_authenticated(client, other, event):
    client.force_login(other)
    other.is_active = False
    other.save()
    resp = client.post(reverse("events:register", args=[event.public_id]))
    assert resp.status_code == 302  # відправлено на логін
    assert not Registration.objects.exists()


# --- Матриця через HTTP ---

ACTIONS = {
    # назва: (метод, url-імʼя, дані)
    "detail": ("get", "events:detail", None),
    "cover": ("get", "events:cover", None),
    "register": ("post", "events:register", {}),
    "unregister": ("post", "events:unregister", {}),
    "comment": ("post", "events:comment_add", {"text": "привіт"}),
    "edit_get": ("get", "events:edit", None),
    "edit_post": ("post", "events:edit", "EVENT_DATA"),
    "delete_get": ("get", "events:delete", None),
    "delete_post": ("post", "events:delete", {}),
    "regenerate": ("post", "events:regenerate_invite", {}),
}


def _call(client, action, event):
    method, name, data = ACTIONS[action]
    url = reverse(name, args=[event.public_id])
    if data == "EVENT_DATA":
        data = event_post_data(title="Зламано")
    return getattr(client, method)(url, data) if method == "post" else client.get(url)


@pytest.fixture
def with_cover(private_event, event):
    for ev in (private_event, event):
        ev.cover.save("c.png", ContentFile(image_bytes()), save=True)


@pytest.mark.parametrize("action", list(ACTIONS))
def test_private_event_stranger_gets_404_everywhere(client, other, private_event, with_cover, action):
    client.force_login(other)
    assert _call(client, action, private_event).status_code == 404


@pytest.mark.parametrize("action", ["detail", "cover"])
def test_private_event_anonymous_404(client, private_event, with_cover, action):
    assert _call(client, action, private_event).status_code == 404


@pytest.mark.parametrize("action", ["register", "unregister", "comment", "edit_get", "edit_post", "delete_get", "delete_post", "regenerate"])
def test_anonymous_redirected_to_login(client, event, action):
    resp = _call(client, action, event)
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp["Location"]


@pytest.mark.parametrize("action", ["edit_get", "edit_post", "delete_get", "delete_post", "regenerate"])
def test_public_event_non_author_403_on_author_actions(client, other, event, action):
    client.force_login(other)
    assert _call(client, action, event).status_code == 403


@pytest.mark.parametrize("action", ["edit_get", "edit_post", "delete_get", "delete_post", "regenerate"])
def test_private_guest_with_access_gets_404_on_author_actions(client, guest, private_event, action):
    client.force_login(guest)
    old_token = private_event.invite_token
    assert _call(client, action, private_event).status_code == 404
    private_event.refresh_from_db()
    assert private_event.title == "Секретна вечірка"
    assert private_event.invite_token == old_token


@pytest.mark.parametrize("action", ["detail", "cover"])
def test_private_guest_can_view(client, guest, private_event, with_cover, action):
    client.force_login(guest)
    assert _call(client, action, private_event).status_code == 200


def test_state_unchanged_after_stranger_attacks(client, other, private_event, event):
    client.force_login(other)
    for action in ACTIONS:
        _call(client, action, private_event)
    for action in ("edit_post", "delete_post", "regenerate"):
        _call(client, action, event)
    assert Event.objects.count() == 2
    assert not Registration.objects.exists()
    assert not Comment.objects.filter(event=private_event).exists()
    assert set(Event.objects.values_list("title", flat=True)) == {"Секретна вечірка", "Публічна подія"}


@pytest.mark.parametrize("bad", ["123", "not-a-uuid", "00000000-0000-0000-0000-000000000000"])
def test_bad_or_unknown_ids_404(client, bad):
    assert client.get(f"/events/{bad}/").status_code == 404
