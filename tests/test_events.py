from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from events.models import Event, Registration
from tests.conftest import event_post_data, make_event, make_user

pytestmark = pytest.mark.django_db


def test_anonymous_cannot_create_event(client):
    resp = client.post(reverse("events:create"), event_post_data())
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp["Location"]
    assert not Event.objects.exists()


def test_create_event_sets_author_ignoring_mass_assignment(other_client, other, author):
    data = event_post_data(
        author=str(author.pk), invite_token="hacked", public_id="00000000-0000-0000-0000-000000000000"
    )
    resp = other_client.post(reverse("events:create"), data)
    assert resp.status_code == 302
    event = Event.objects.get()
    assert event.author == other
    assert event.invite_token != "hacked"
    assert str(event.public_id) != "00000000-0000-0000-0000-000000000000"
    assert len(event.invite_token) >= 40


@pytest.mark.parametrize("title", ["", "   "])
def test_blank_title_rejected(author_client, title):
    resp = author_client.post(reverse("events:create"), event_post_data(title=title))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_too_long_fields_rejected(author_client):
    resp = author_client.post(reverse("events:create"), event_post_data(title="x" * 121))
    assert resp.status_code == 200
    resp = author_client.post(reverse("events:create"), event_post_data(description="x" * 5001))
    assert resp.status_code == 200
    assert not Event.objects.exists()


@pytest.mark.parametrize("capacity", ["0", "10001", "-5", "abc"])
def test_capacity_bounds(author_client, capacity):
    resp = author_client.post(reverse("events:create"), event_post_data(capacity=capacity))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_start_must_be_in_future(author_client):
    past = timezone.localtime(timezone.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    resp = author_client.post(reverse("events:create"), event_post_data(starts_at=past))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_event_url_uses_uuid(event, client):
    resp = client.get(f"/events/{event.pk}/")
    assert resp.status_code == 404
    assert client.get(reverse("events:detail", args=[event.public_id])).status_code == 200


def test_home_lists_only_future_public_sorted_and_searchable(client, author):
    later = make_event(author, title="Джаз пізніше", starts_at=timezone.now() + timedelta(days=9))
    sooner = make_event(author, title="Рок раніше", starts_at=timezone.now() + timedelta(days=1))
    make_event(author, title="Джаз минулий", starts_at=timezone.now() - timedelta(days=1))
    make_event(author, title="Джаз приватний", is_private=True)

    resp = client.get(reverse("events:home"))
    events = list(resp.context["page"].object_list)
    assert events == [sooner, later]

    resp = client.get(reverse("events:home"), {"q": "джаз"})
    assert list(resp.context["page"].object_list) == [later]


def test_search_query_truncated(client):
    resp = client.get(reverse("events:home"), {"q": "а" * 500})
    assert resp.status_code == 200
    assert len(resp.context["q"]) == 100


def test_pagination_20_per_page(client, author):
    for i in range(25):
        make_event(author, title=f"E{i}")
    resp = client.get(reverse("events:home"))
    assert len(resp.context["page"].object_list) == 20
    resp = client.get(reverse("events:home"), {"page": 2})
    assert len(resp.context["page"].object_list) == 5


# --- Права автора ---

def test_other_user_cannot_edit_public_event(other_client, event):
    url = reverse("events:edit", args=[event.public_id])
    assert other_client.get(url).status_code == 403
    resp = other_client.post(url, event_post_data(title="Зламано"))
    assert resp.status_code == 403
    event.refresh_from_db()
    assert event.title == "Публічна подія"


def test_other_user_cannot_delete_event(other_client, event):
    resp = other_client.post(reverse("events:delete", args=[event.public_id]))
    assert resp.status_code == 403
    assert Event.objects.filter(pk=event.pk).exists()


def test_anonymous_cannot_delete_event(client, event):
    resp = client.post(reverse("events:delete", args=[event.public_id]))
    assert resp.status_code == 302
    assert Event.objects.filter(pk=event.pk).exists()


def test_other_user_cannot_regenerate_invite(other_client, event):
    old = event.invite_token
    resp = other_client.post(reverse("events:regenerate_invite", args=[event.public_id]))
    assert resp.status_code == 403
    event.refresh_from_db()
    assert event.invite_token == old


def test_author_can_edit_and_delete(author_client, event):
    resp = author_client.post(
        reverse("events:edit", args=[event.public_id]), event_post_data(title="Оновлено")
    )
    assert resp.status_code == 302
    event.refresh_from_db()
    assert event.title == "Оновлено"
    resp = author_client.post(reverse("events:delete", args=[event.public_id]))
    assert resp.status_code == 302
    assert not Event.objects.filter(pk=event.pk).exists()


def test_delete_get_does_not_delete(author_client, event):
    resp = author_client.get(reverse("events:delete", args=[event.public_id]))
    assert resp.status_code == 200
    assert Event.objects.filter(pk=event.pk).exists()


def test_edit_cannot_change_author(author_client, event, other):
    author_client.post(
        reverse("events:edit", args=[event.public_id]), event_post_data(author=str(other.pk))
    )
    event.refresh_from_db()
    assert event.author_id != other.pk


def test_participants_visible_only_to_author(client, author, other, event):
    third = make_user("third@example.com", "Третій")
    Registration.objects.create(event=event, user=third)
    url = reverse("events:detail", args=[event.public_id])

    client.force_login(other)
    html = client.get(url).content.decode()
    assert "third@example.com" not in html
    assert "вільно" in html

    client.force_login(author)
    html = client.get(url).content.decode()
    assert "third@example.com" in html
    assert "Третій" in html


def test_cannot_reduce_capacity_below_registered(author_client, event):
    for i in range(3):
        Registration.objects.create(event=event, user=make_user(f"p{i}@example.com"))
    resp = author_client.post(
        reverse("events:edit", args=[event.public_id]), event_post_data(capacity="2")
    )
    assert resp.status_code == 200
    assert "нижче кількості записаних" in resp.content.decode()
    event.refresh_from_db()
    assert event.capacity == 10
    resp = author_client.post(
        reverse("events:edit", args=[event.public_id]), event_post_data(capacity="3")
    )
    assert resp.status_code == 302


def test_edit_date_cannot_move_to_past(author_client, event):
    past = timezone.localtime(timezone.now() - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    resp = author_client.post(
        reverse("events:edit", args=[event.public_id]), event_post_data(starts_at=past)
    )
    assert resp.status_code == 200
    event.refresh_from_db()
    assert event.starts_at > timezone.now()


def test_profile_shows_created_and_registered(client, author, other):
    mine_private_past = make_event(
        author, title="Моя минула приватна", is_private=True, starts_at=timezone.now() - timedelta(days=2)
    )
    theirs = make_event(other, title="Чужа подія")
    Registration.objects.create(event=theirs, user=author)
    client.force_login(author)
    resp = client.get(reverse("events:profile"))
    assert mine_private_past in resp.context["created"]
    assert theirs in resp.context["registered"]
    assert "author@example.com" in resp.content.decode()


def test_profile_requires_login(client):
    assert client.get(reverse("events:profile")).status_code == 302


def test_custom_404_page(client):
    resp = client.get("/no-such-page/")
    assert resp.status_code == 404
    assert "Сторінку не знайдено" in resp.content.decode()


# --- Лендінг ---

def test_landing_featured_is_nearest_public_event(client, author):
    make_event(author, title="Приватна найближча", is_private=True, starts_at=timezone.now() + timedelta(hours=1))
    make_event(author, title="Минула", starts_at=timezone.now() - timedelta(hours=1))
    nearest = make_event(author, title="Публічна найближча", starts_at=timezone.now() + timedelta(hours=5))
    make_event(author, title="Пізніша", starts_at=timezone.now() + timedelta(days=5))
    resp = client.get(reverse("events:home"))
    assert resp.context["featured"] == nearest
    html = resp.content.decode()
    assert "Приватна найближча" not in html
    assert "Найближча тусовка" in html


def test_landing_featured_seats(client, author, other):
    event = make_event(author, capacity=4)
    Registration.objects.create(event=event, user=other)
    resp = client.get(reverse("events:home"))
    assert resp.context["featured_free"] == 3


def test_landing_hidden_on_search_and_when_only_private(client, author):
    make_event(author, title="Секрет", is_private=True)
    resp = client.get(reverse("events:home"))
    assert "featured" not in resp.context
    assert "Секрет" not in resp.content.decode()
    resp = client.get(reverse("events:home"), {"q": "x"})
    assert resp.context["show_landing"] is False


def test_landing_guest_vs_logged_in(client, author):
    html = client.get(reverse("events:home")).content.decode()
    assert "Створити акаунт" in html
    client.force_login(author)
    html = client.get(reverse("events:home")).content.decode()
    assert "Привіт, Автор" in html
    assert "Створити акаунт" not in html
