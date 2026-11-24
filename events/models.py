import secrets
import uuid
from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

CAPACITY_MIN = 1
CAPACITY_MAX = 10000
ALLOWED_COVER_EXTENSIONS = {"jpg", "png", "webp"}


def generate_invite_token():
    return secrets.token_urlsafe(32)


def cover_upload_to(instance, filename):
    """Імʼя файлу генеруємо самі; від клієнтського імені беремо лише перевірене розширення."""
    ext = PurePath(filename).suffix.lower().lstrip(".")
    if ext not in ALLOWED_COVER_EXTENSIONS:
        ext = "bin"
    return f"covers/{uuid.uuid4()}.{ext}"


def validate_not_blank(value):
    if not (value or "").strip():
        raise ValidationError("Поле не може бути порожнім.")


class Event(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authored_events",
        verbose_name="автор",
    )
    title = models.CharField("назва", max_length=120, validators=[validate_not_blank])
    description = models.TextField("опис", max_length=5000, blank=True)
    starts_at = models.DateTimeField("початок")
    capacity = models.PositiveIntegerField(
        "кількість місць",
        validators=[MinValueValidator(CAPACITY_MIN), MaxValueValidator(CAPACITY_MAX)],
    )
    cover = models.ImageField("обкладинка", upload_to=cover_upload_to, blank=True)
    is_private = models.BooleanField("приватна подія", default=False)
    invite_token = models.CharField(
        max_length=64, unique=True, default=generate_invite_token, editable=False
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["starts_at"]
        verbose_name = "подія"
        verbose_name_plural = "події"
        indexes = [models.Index(fields=["is_private", "starts_at"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gte=CAPACITY_MIN) & Q(capacity__lte=CAPACITY_MAX),
                name="event_capacity_range",
            ),
        ]

    def __str__(self):
        return self.title

    def regenerate_invite_token(self):
        self.invite_token = generate_invite_token()
        self.save(update_fields=["invite_token", "updated_at"])


class Registration(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="registrations"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="unique_registration"),
        ]

    def __str__(self):
        return f"{self.user} → {self.event}"


class PrivateAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="private_accesses"
    )
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="private_accesses")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="unique_private_access"),
        ]


class Comment(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    text = models.TextField("коментар", max_length=2000, validators=[validate_not_blank])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
