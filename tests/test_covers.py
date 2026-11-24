from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from events.models import Event
from tests.conftest import event_post_data, image_bytes

pytestmark = pytest.mark.django_db


def upload(name, content, content_type="image/jpeg"):
    return SimpleUploadedFile(name, content, content_type=content_type)


def create(client, cover):
    return client.post(reverse("events:create"), {**event_post_data(), "cover": cover})


@pytest.mark.parametrize("fmt,ext", [("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")])
def test_valid_cover_saved_with_generated_name(author_client, fmt, ext):
    resp = create(author_client, upload("../../evil name.php", image_bytes(fmt)))
    assert resp.status_code == 302
    event = Event.objects.get()
    assert event.cover.name.startswith("covers/")
    assert event.cover.name.endswith(f".{ext}")
    assert "evil" not in event.cover.name


def test_svg_rejected(author_client):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    resp = create(author_client, upload("pic.svg", svg, "image/svg+xml"))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_fake_jpg_rejected(author_client):
    resp = create(author_client, upload("photo.jpg", b"<html><script>alert(1)</script></html>"))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_gif_rejected(author_client):
    resp = create(author_client, upload("anim.jpg", image_bytes("GIF"), "image/jpeg"))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_too_large_file_rejected(author_client, settings):
    settings.COVER_MAX_BYTES = 1000
    resp = create(author_client, upload("big.png", image_bytes("PNG", (400, 400)) + b"\0" * 2000, "image/png"))
    assert resp.status_code == 200
    assert "завеликий" in resp.content.decode()
    assert not Event.objects.exists()


def test_request_body_over_limit_rejected(author_client, settings):
    settings.REQUEST_BODY_MAX_BYTES = 10_000
    resp = create(author_client, upload("big.png", b"\0" * 20_000, "image/png"))
    assert resp.status_code == 413


def test_too_many_pixels_rejected(author_client, settings):
    settings.COVER_MAX_DIMENSION = 50
    resp = create(author_client, upload("wide.png", image_bytes("PNG", (60, 10)), "image/png"))
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_cover_served_with_headers(author_client):
    create(author_client, upload("a.png", image_bytes("PNG"), "image/png"))
    event = Event.objects.get()
    resp = author_client.get(reverse("events:cover", args=[event.public_id]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == "image/png"
    assert resp["X-Content-Type-Options"] == "nosniff"


def test_no_cover_404(client, event):
    assert client.get(reverse("events:cover", args=[event.public_id])).status_code == 404


def test_old_cover_deleted_on_replace_and_on_event_delete(author_client, settings, django_capture_on_commit_callbacks):
    create(author_client, upload("a.png", image_bytes("PNG"), "image/png"))
    event = Event.objects.get()
    old_path = Path(settings.MEDIA_ROOT) / event.cover.name
    assert old_path.exists()

    url = reverse("events:edit", args=[event.public_id])
    data = {**event_post_data(), "cover": upload("b.jpg", image_bytes("JPEG"))}
    with django_capture_on_commit_callbacks(execute=True):
        resp = author_client.post(url, data)
    assert resp.status_code == 302
    event.refresh_from_db()
    new_path = Path(settings.MEDIA_ROOT) / event.cover.name
    assert new_path.exists()
    assert not old_path.exists()

    with django_capture_on_commit_callbacks(execute=True):
        author_client.post(reverse("events:delete", args=[event.public_id]))
    assert not new_path.exists()


def test_cover_cleared_deletes_file(author_client, settings, django_capture_on_commit_callbacks):
    create(author_client, upload("a.png", image_bytes("PNG"), "image/png"))
    event = Event.objects.get()
    path = Path(settings.MEDIA_ROOT) / event.cover.name
    with django_capture_on_commit_callbacks(execute=True):
        resp = author_client.post(
            reverse("events:edit", args=[event.public_id]), {**event_post_data(), "cover-clear": "on"}
        )
    assert resp.status_code == 302
    event.refresh_from_db()
    assert not event.cover
    assert not path.exists()


def test_media_not_served_publicly(client, author_client, settings):
    create(author_client, upload("a.png", image_bytes("PNG"), "image/png"))
    event = Event.objects.get()
    assert client.get("/media/" + event.cover.name).status_code == 404
    assert client.get("/media-not-served/" + event.cover.name).status_code == 404
