import io
import struct
import zlib
from pathlib import Path

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from events.models import Event, PrivateAccess
from tests.conftest import event_post_data, image_bytes, make_event

pytestmark = pytest.mark.django_db


def create(client, name, content, ctype="image/png"):
    return client.post(
        reverse("events:create"),
        {**event_post_data(), "cover": SimpleUploadedFile(name, content, content_type=ctype)},
    )


def png_with_header_size(width, height):
    """Валідний PNG-заголовок із заявленим розміром — класична decompression bomb."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\0" * 10)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


@pytest.mark.parametrize(
    "name,content,ctype",
    [
        ("empty.png", b"", "image/png"),
        ("page.png", b"<!doctype html><script>alert(1)</script>", "image/png"),
        ("doc.jpg", b"%PDF-1.4\n%fake pdf", "image/jpeg"),
        ("anim.gif", None, "image/gif"),
        ("pic.bmp", None, "image/bmp"),
        ("pic.tiff", None, "image/tiff"),
        ("bomb.png", png_with_header_size(50000, 50000), "image/png"),
        ("wide.png", png_with_header_size(6001, 10), "image/png"),
    ],
)
def test_rejected_uploads(author_client, name, content, ctype):
    if content is None:
        fmt = {"gif": "GIF", "bmp": "BMP", "tiff": "TIFF"}[name.rsplit(".", 1)[1]]
        content = image_bytes(fmt)
    resp = create(author_client, name, content, ctype)
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_truncated_png_rejected(author_client):
    data = image_bytes("PNG", (200, 200))
    resp = create(author_client, "cut.png", data[: len(data) // 2])
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_svg_disguised_as_png_rejected(author_client):
    svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>'
    resp = create(author_client, "x.png", svg, "image/png")
    assert resp.status_code == 200
    assert not Event.objects.exists()


def test_image_with_appended_html_is_saved_but_served_as_image(author_client):
    """Поліглот: валідний PNG + HTML у хвості. Приймається як PNG, але віддається як image/png + nosniff."""
    content = image_bytes("PNG") + b"<script>alert(1)</script>"
    create(author_client, "poly.html", content)
    event = Event.objects.get()
    assert event.cover.name.endswith(".png")
    resp = author_client.get(reverse("events:cover", args=[event.public_id]))
    assert resp["Content-Type"] == "image/png"
    assert resp["X-Content-Type-Options"] == "nosniff"


def test_png_bytes_with_jpg_name_saved_as_png(author_client):
    create(author_client, "photo.jpg", image_bytes("PNG"), "image/jpeg")
    assert Event.objects.get().cover.name.endswith(".png")


def test_exactly_max_dimension_accepted(author_client, settings):
    settings.COVER_MAX_DIMENSION = 40
    resp = create(author_client, "ok.png", image_bytes("PNG", (40, 40)))
    assert resp.status_code == 302


@pytest.mark.parametrize("fmt,ctype", [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_cover_content_types(author_client, fmt, ctype):
    create(author_client, "c", image_bytes(fmt), ctype)
    event = Event.objects.get()
    resp = author_client.get(reverse("events:cover", args=[event.public_id]))
    assert resp.status_code == 200
    assert resp["Content-Type"] == ctype
    data = b"".join(resp.streaming_content)
    assert Image.open(io.BytesIO(data)).format == fmt


def test_public_cover_visible_to_anonymous_with_public_cache(client, author):
    event = make_event(author)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    resp = client.get(reverse("events:cover", args=[event.public_id]))
    assert resp.status_code == 200
    assert "public" in resp["Cache-Control"]


def test_private_cover_after_invite_has_private_cache(client, author, other):
    event = make_event(author, is_private=True)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    PrivateAccess.objects.create(user=other, event=event)
    client.force_login(other)
    resp = client.get(reverse("events:cover", args=[event.public_id]))
    assert resp.status_code == 200
    assert "private" in resp["Cache-Control"]


def test_cover_missing_on_disk_returns_404(client, author, settings):
    event = make_event(author)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    (Path(settings.MEDIA_ROOT) / event.cover.name).unlink()
    assert client.get(reverse("events:cover", args=[event.public_id])).status_code == 404


def test_cover_with_unexpected_extension_not_served(client, author):
    event = make_event(author)
    event.cover.save("c.bin", ContentFile(b"<script>alert(1)</script>"), save=True)
    assert client.get(reverse("events:cover", args=[event.public_id])).status_code == 404


def test_cover_post_not_allowed(client, author):
    event = make_event(author)
    event.cover.save("c.png", ContentFile(image_bytes()), save=True)
    assert client.post(reverse("events:cover", args=[event.public_id])).status_code == 405


def test_invalid_upload_on_edit_keeps_old_cover(author_client, settings):
    create(author_client, "a.png", image_bytes("PNG"))
    event = Event.objects.get()
    old_name = event.cover.name
    resp = author_client.post(
        reverse("events:edit", args=[event.public_id]),
        {**event_post_data(), "cover": SimpleUploadedFile("x.png", b"nope", content_type="image/png")},
    )
    assert resp.status_code == 200
    event.refresh_from_db()
    assert event.cover.name == old_name
    assert (Path(settings.MEDIA_ROOT) / old_name).exists()


def test_failed_capacity_edit_does_not_delete_cover(author_client, settings, django_capture_on_commit_callbacks):
    from events.models import Registration
    from tests.conftest import make_user

    create(author_client, "a.png", image_bytes("PNG"))
    event = Event.objects.get()
    old = Path(settings.MEDIA_ROOT) / event.cover.name
    for i in range(3):
        Registration.objects.create(event=event, user=make_user(f"z{i}@example.com"))
    with django_capture_on_commit_callbacks(execute=True):
        resp = author_client.post(
            reverse("events:edit", args=[event.public_id]),
            {**event_post_data(capacity="1"), "cover": SimpleUploadedFile("b.png", image_bytes("PNG"), content_type="image/png")},
        )
    assert resp.status_code == 200
    assert old.exists()
