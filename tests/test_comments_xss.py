import pytest
from django.urls import reverse

from events.models import Comment
from tests.conftest import event_post_data, make_event

pytestmark = pytest.mark.django_db

XSS = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def test_anonymous_cannot_comment(client, event):
    resp = client.post(reverse("events:comment_add", args=[event.public_id]), {"text": "hi"})
    assert resp.status_code == 302
    assert not Comment.objects.exists()


def test_comment_added_and_blank_rejected(other_client, event):
    url = reverse("events:comment_add", args=[event.public_id])
    other_client.post(url, {"text": "   "})
    assert not Comment.objects.exists()
    other_client.post(url, {"text": "Привіт"})
    assert Comment.objects.count() == 1


def test_comment_too_long_rejected(other_client, event):
    other_client.post(reverse("events:comment_add", args=[event.public_id]), {"text": "x" * 2001})
    assert not Comment.objects.exists()


def test_comment_rate_limit(other_client, event):
    url = reverse("events:comment_add", args=[event.public_id])
    other_client.post(url, {"text": "1"})
    resp = other_client.post(url, {"text": "2"}, follow=True)
    assert "Занадто часто" in resp.content.decode()
    assert Comment.objects.count() == 1


def test_comment_get_not_allowed(other_client, event):
    assert other_client.get(reverse("events:comment_add", args=[event.public_id])).status_code == 405


def test_xss_escaped_in_title_description_comment(client, author, other):
    event = make_event(author, title=XSS, description=XSS + "\nрядок2")
    Comment.objects.create(event=event, author=other, text=XSS)
    other.name = "<b>bold</b>"
    other.save()
    html = client.get(reverse("events:detail", args=[event.public_id])).content.decode()
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "<b>bold</b>" not in html
    assert "&lt;script&gt;" in html
    assert "<br>рядок2" in html  # linebreaksbr працює
    home = client.get(reverse("events:home")).content.decode()
    assert "<script>alert" not in home


def test_xss_via_form_submission_escaped(author_client):
    author_client.post(reverse("events:create"), event_post_data(title=XSS))
    html = author_client.get(reverse("events:home")).content.decode()
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html
