from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from events.models import Event, PrivateAccess, Registration
from tests.conftest import PASSWORD, event_post_data, make_event, make_user

pytestmark = pytest.mark.django_db


# --- Головна ---

@pytest.mark.parametrize("page", ["abc", "0", "-1", "999", ""])
def test_bad_page_param_does_not_crash(client, author, page):
    for i in range(3):
        make_event(author, title=f"E{i}")
    assert client.get(reverse("events:home"), {"page": page}).status_code == 200


def test_whitespace_query_is_ignored(client, event):
    resp = client.get(reverse("events:home"), {"q": "    "})
    assert resp.context["q"] == ""
    assert event in resp.context["page"].object_list


def test_search_is_case_insensitive_and_partial(client, author):
    e = make_event(author, title="Вечір Джазу на Подолі")
    for q in ("джаз", "ДЖАЗ", "подол", "Вечір"):
        assert e in client.get(reverse("events:home"), {"q": q}).context["page"].object_list


def test_search_with_sql_wildcards_is_literal(client, author):
    make_event(author, title="Звичайна")
    resp = client.get(reverse("events:home"), {"q": "%"})
    assert list(resp.context["page"].object_list) == []
    resp = client.get(reverse("events:home"), {"q": "_"})
    assert list(resp.context["page"].object_list) == []


def test_event_starting_now_not_listed(client, author):
    make_event(author, starts_at=timezone.now() - timedelta(seconds=1))
    assert list(client.get(reverse("events:home")).context["page"].object_list) == []


def test_post_to_home_not_allowed(client):
    assert client.post(reverse("events:home")).status_code == 405


def test_private_pagination_never_leaks(client, author):
    for i in range(25):
        make_event(author, title=f"Приватна {i}", is_private=True)
    make_event(author, title="Єдина публічна")
    resp = client.get(reverse("events:home"))
    assert [e.title for e in resp.context["page"].object_list] == ["Єдина публічна"]
    assert resp.context["page"].paginator.count == 1


# --- Створення / редагування ---

def test_create_form_get_requires_login(client):
    resp = client.get(reverse("events:create"))
    assert resp.status_code == 302


def test_create_private_event(author_client, author):
    author_client.post(reverse("events:create"), event_post_data(is_private="on"))
    event = Event.objects.get()
    assert event.is_private
    assert event.author == author


@pytest.mark.parametrize("starts_at", ["", "not-a-date", "2020-13-45T25:61"])
def test_invalid_dates_rejected(author_client, starts_at):
    resp = author_client.post(reverse("events:create"), event_post_data(starts_at=starts_at))
    assert resp.status_code == 200
    assert not Event.objects.exists()


@pytest.mark.parametrize("capacity", ["1", "10000"])
def test_capacity_boundaries_accepted(author_client, capacity):
    resp = author_client.post(reverse("events:create"), event_post_data(capacity=capacity))
    assert resp.status_code == 302


def test_title_and_description_trimmed(author_client):
    author_client.post(reverse("events:create"), event_post_data(title="  Назва  ", description="  опис \n"))
    event = Event.objects.get()
    assert event.title == "Назва"
    assert event.description == "опис"


def test_title_exactly_120_ok_and_description_5000_ok(author_client):
    resp = author_client.post(reverse("events:create"), event_post_data(title="x" * 120, description="y" * 5000))
    assert resp.status_code == 302


def test_edit_past_event_without_changing_date_allowed(author_client, author):
    past = make_event(author, starts_at=timezone.now() - timedelta(days=1))
    data = event_post_data(
        title="Звіт про подію",
        starts_at=timezone.localtime(past.starts_at).strftime("%Y-%m-%dT%H:%M"),
    )
    resp = author_client.post(reverse("events:edit", args=[past.public_id]), data)
    assert resp.status_code == 302
    past.refresh_from_db()
    assert past.title == "Звіт про подію"


def test_edit_ignores_invite_token_and_public_id(author_client, event):
    token, pid = event.invite_token, event.public_id
    author_client.post(
        reverse("events:edit", args=[event.public_id]),
        event_post_data(invite_token="x", public_id="00000000-0000-0000-0000-000000000000"),
    )
    event.refresh_from_db()
    assert event.invite_token == token
    assert event.public_id == pid


def test_switch_public_to_private_hides_it(author_client, client, event):
    author_client.post(reverse("events:edit", args=[event.public_id]), event_post_data(is_private="on"))
    event.refresh_from_db()
    assert event.is_private
    client.logout()
    assert client.get(reverse("events:detail", args=[event.public_id])).status_code == 404


def test_capacity_equal_to_registered_allowed(author_client, event):
    for i in range(2):
        Registration.objects.create(event=event, user=make_user(f"r{i}@example.com"))
    resp = author_client.post(reverse("events:edit", args=[event.public_id]), event_post_data(capacity="2"))
    assert resp.status_code == 302


# --- Запис ---

def test_full_event_message(client, author):
    event = make_event(author, capacity=1)
    Registration.objects.create(event=event, user=make_user("a@example.com"))
    client.force_login(make_user("b@example.com"))
    resp = client.post(reverse("events:register", args=[event.public_id]), follow=True)
    assert "вільних місць немає" in resp.content.decode()


def test_cancel_frees_seat(client, author):
    event = make_event(author, capacity=1)
    a = make_user("a@example.com")
    b = make_user("b@example.com")
    client.force_login(a)
    client.post(reverse("events:register", args=[event.public_id]))
    client.post(reverse("events:unregister", args=[event.public_id]))
    client.force_login(b)
    client.post(reverse("events:register", args=[event.public_id]))
    assert list(Registration.objects.values_list("user__email", flat=True)) == ["b@example.com"]


def test_cannot_cancel_after_start(client, author, other):
    past = make_event(author, starts_at=timezone.now() - timedelta(hours=1))
    Registration.objects.create(event=past, user=other)
    client.force_login(other)
    resp = client.post(reverse("events:unregister", args=[past.public_id]), follow=True)
    assert "вже почалась" in resp.content.decode()
    assert Registration.objects.filter(event=past, user=other).exists()


def test_cancel_when_not_registered(other_client, event):
    resp = other_client.post(reverse("events:unregister", args=[event.public_id]), follow=True)
    assert "не були записані" in resp.content.decode()


def test_detail_seat_counter(client, author):
    event = make_event(author, capacity=5)
    for i in range(2):
        Registration.objects.create(event=event, user=make_user(f"s{i}@example.com"))
    resp = client.get(reverse("events:detail", args=[event.public_id]))
    assert resp.context["free"] == 3
    assert "вільно <strong>3</strong> з 5" in resp.content.decode()


def test_author_does_not_see_go_button(author_client, event):
    html = author_client.get(reverse("events:detail", args=[event.public_id])).content.decode()
    assert reverse("events:register", args=[event.public_id]) not in html


# --- Інвайти: повний сценарій через логін ---

def test_invite_full_flow_through_login(client, private_event):
    make_user("guest@example.com", "Гість")
    invite = reverse("events:invite", args=[private_event.invite_token])
    resp = client.get(invite)
    login_url = resp["Location"]
    resp = client.post(login_url, {"username": "guest@example.com", "password": PASSWORD})
    assert resp.status_code == 302
    assert resp["Location"] == invite
    resp = client.get(invite)
    assert resp["Location"] == reverse("events:detail", args=[private_event.public_id])
    assert client.get(resp["Location"]).status_code == 200


def test_author_opening_own_invite_creates_no_access(author_client, private_event):
    resp = author_client.get(reverse("events:invite", args=[private_event.invite_token]))
    assert resp.status_code == 302
    assert not PrivateAccess.objects.exists()


def test_public_event_invite_creates_no_access(other_client, event):
    resp = other_client.get(reverse("events:invite", args=[event.invite_token]))
    assert resp.status_code == 302
    assert not PrivateAccess.objects.exists()


def test_invite_post_not_allowed(other_client, private_event):
    resp = other_client.post(reverse("events:invite", args=[private_event.invite_token]))
    assert resp.status_code == 405
    assert not PrivateAccess.objects.exists()


def test_invite_token_prefix_does_not_work(other_client, private_event):
    resp = other_client.get(reverse("events:invite", args=[private_event.invite_token[:-1]]))
    assert resp.status_code == 404


def test_access_kept_after_regenerate(author_client, other, private_event, client):
    PrivateAccess.objects.create(user=other, event=private_event)
    author_client.post(reverse("events:regenerate_invite", args=[private_event.public_id]))
    client.force_login(other)
    assert client.get(reverse("events:detail", args=[private_event.public_id])).status_code == 200


# --- Профіль / акаунти ---

def test_profile_does_not_show_others_events(client, author, other):
    make_event(other, title="Чужа приватна", is_private=True)
    client.force_login(author)
    html = client.get(reverse("events:profile")).content.decode()
    assert "Чужа приватна" not in html
    assert "other@example.com" not in html


def test_signup_page_redirects_logged_in(author_client):
    assert author_client.get(reverse("accounts:signup")).status_code == 302


def test_login_page_redirects_logged_in(author_client):
    assert author_client.get(reverse("accounts:login")).status_code == 302


@pytest.mark.parametrize(
    "data",
    [
        {"email": "bad-email", "name": "A", "password1": PASSWORD, "password2": PASSWORD},
        {"email": "a@example.com", "name": "я" * 51, "password1": PASSWORD, "password2": PASSWORD},
        {"email": "a@example.com", "name": "A", "password1": PASSWORD, "password2": PASSWORD + "x"},
        {"email": "a@example.com", "name": "A", "password1": "password", "password2": "password"},
        {"email": "a@example.com", "name": "A", "password1": "a@example.com", "password2": "a@example.com"},
        {"email": "", "name": "A", "password1": PASSWORD, "password2": PASSWORD},
    ],
)
def test_signup_validation_errors(client, data):
    resp = client.post(reverse("accounts:signup"), data)
    assert resp.status_code == 200
    assert not User.objects.exists()


def test_signup_ignores_is_staff_mass_assignment(client):
    client.post(
        reverse("accounts:signup"),
        {"email": "a@example.com", "name": "A", "password1": PASSWORD, "password2": PASSWORD,
         "is_staff": "on", "is_superuser": "on"},
    )
    user = User.objects.get()
    assert not user.is_staff and not user.is_superuser


def test_password_is_hashed(client):
    client.post(
        reverse("accounts:signup"),
        {"email": "a@example.com", "name": "A", "password1": PASSWORD, "password2": PASSWORD},
    )
    user = User.objects.get()
    assert user.password != PASSWORD
    assert user.check_password(PASSWORD)
