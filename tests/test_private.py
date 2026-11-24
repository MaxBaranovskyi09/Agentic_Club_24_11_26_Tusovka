import pytest
from django.urls import reverse

from events.models import Comment, PrivateAccess, Registration
from tests.conftest import image_bytes, make_event
from django.core.files.base import ContentFile

pytestmark = pytest.mark.django_db


def test_private_not_in_list_or_search(client, private_event, event):
    resp = client.get(reverse("events:home"))
    assert private_event not in resp.context["page"].object_list
    assert event in resp.context["page"].object_list
    resp = client.get(reverse("events:home"), {"q": "Секретна"})
    assert list(resp.context["page"].object_list) == []
    assert "Секретна" not in resp.content.decode().split("Результати")[-1].split("</main>")[0].replace("«Секретна»", "")


def test_private_without_access_returns_404_everywhere(other_client, other, private_event):
    pid = private_event.public_id
    private_event.cover.save("x.png", ContentFile(image_bytes()), save=True)
    assert other_client.get(reverse("events:detail", args=[pid])).status_code == 404
    assert other_client.post(reverse("events:register", args=[pid])).status_code == 404
    assert other_client.post(reverse("events:unregister", args=[pid])).status_code == 404
    assert other_client.post(reverse("events:comment_add", args=[pid]), {"text": "hi"}).status_code == 404
    assert other_client.get(reverse("events:cover", args=[pid])).status_code == 404
    assert other_client.get(reverse("events:edit", args=[pid])).status_code == 404
    assert other_client.post(reverse("events:delete", args=[pid])).status_code == 404
    assert other_client.post(reverse("events:regenerate_invite", args=[pid])).status_code == 404
    assert not Registration.objects.exists()
    assert not Comment.objects.exists()


def test_private_anonymous_404(client, private_event):
    assert client.get(reverse("events:detail", args=[private_event.public_id])).status_code == 404
    assert client.get(reverse("events:cover", args=[private_event.public_id])).status_code == 404


def test_invite_grants_access(other_client, other, private_event):
    resp = other_client.get(reverse("events:invite", args=[private_event.invite_token]))
    assert resp.status_code == 302
    assert resp["Location"] == reverse("events:detail", args=[private_event.public_id])
    assert PrivateAccess.objects.filter(user=other, event=private_event).exists()
    assert other_client.get(resp["Location"]).status_code == 200
    resp = other_client.post(reverse("events:register", args=[private_event.public_id]))
    assert Registration.objects.filter(user=other, event=private_event).exists()
    other_client.post(reverse("events:comment_add", args=[private_event.public_id]), {"text": "Іду!"})
    assert Comment.objects.filter(event=private_event).exists()


def test_invite_twice_is_idempotent(other_client, other, private_event):
    url = reverse("events:invite", args=[private_event.invite_token])
    other_client.get(url)
    other_client.get(url)
    assert PrivateAccess.objects.filter(user=other, event=private_event).count() == 1


def test_invite_anonymous_redirects_to_login_with_next(client, other, private_event):
    url = reverse("events:invite", args=[private_event.invite_token])
    resp = client.get(url)
    assert resp.status_code == 302
    assert reverse("accounts:login") in resp["Location"]
    assert "next=" in resp["Location"]
    client.force_login(other)
    resp = client.get(url)
    assert PrivateAccess.objects.filter(user=other, event=private_event).exists()


def test_invalid_invite_404(other_client):
    assert other_client.get(reverse("events:invite", args=["nope"])).status_code == 404


def test_regenerate_invalidates_old_token(author_client, private_event, other, client):
    old = private_event.invite_token
    resp = author_client.post(reverse("events:regenerate_invite", args=[private_event.public_id]))
    assert resp.status_code == 302
    private_event.refresh_from_db()
    assert private_event.invite_token != old
    client.force_login(other)
    assert client.get(reverse("events:invite", args=[old])).status_code == 404
    assert not PrivateAccess.objects.filter(user=other).exists()
    assert client.get(reverse("events:invite", args=[private_event.invite_token])).status_code == 302


def test_regenerate_via_get_not_allowed(author_client, private_event):
    old = private_event.invite_token
    resp = author_client.get(reverse("events:regenerate_invite", args=[private_event.public_id]))
    assert resp.status_code == 405
    private_event.refresh_from_db()
    assert private_event.invite_token == old


def test_author_sees_invite_link(author_client, private_event):
    html = author_client.get(reverse("events:detail", args=[private_event.public_id])).content.decode()
    assert private_event.invite_token in html


def test_non_author_with_access_does_not_see_invite_or_participants(other_client, other, author, private_event):
    PrivateAccess.objects.create(user=other, event=private_event)
    html = other_client.get(reverse("events:detail", args=[private_event.public_id])).content.decode()
    assert private_event.invite_token not in html
    assert "author@example.com" not in html


def test_invite_for_public_event_token_not_leaked(other_client, event):
    html = other_client.get(reverse("events:detail", args=[event.public_id])).content.decode()
    assert event.invite_token not in html
