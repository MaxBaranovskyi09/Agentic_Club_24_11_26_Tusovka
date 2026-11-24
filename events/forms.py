from django import forms
from django.core.files.uploadedfile import UploadedFile
from django.utils import timezone

from .models import CAPACITY_MAX, CAPACITY_MIN, Comment, Event
from .validators import validate_cover_image

DATETIME_INPUT_FORMAT = "%Y-%m-%dT%H:%M"


class EventForm(forms.ModelForm):
    """Явний список полів: author, invite_token, public_id ніколи не беруться з запиту."""

    class Meta:
        model = Event
        fields = ["title", "description", "starts_at", "capacity", "cover", "is_private"]
        labels = {
            "title": "Назва",
            "description": "Опис",
            "starts_at": "Дата і час початку",
            "capacity": "Кількість місць",
            "cover": "Обкладинка (JPEG, PNG або WebP, до 5 МБ)",
            "is_private": "Приватна подія (доступ лише за інвайт-посиланням)",
        }
        widgets = {
            "title": forms.TextInput(attrs={"maxlength": 120, "autocomplete": "off"}),
            "description": forms.Textarea(attrs={"rows": 8, "maxlength": 5000}),
            "starts_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format=DATETIME_INPUT_FORMAT
            ),
            "capacity": forms.NumberInput(attrs={"min": CAPACITY_MIN, "max": CAPACITY_MAX}),
            "cover": forms.ClearableFileInput(
                attrs={"accept": "image/jpeg,image/png,image/webp"}
            ),
        }

    def __init__(self, *args, registered_count=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.registered_count = registered_count
        self.fields["starts_at"].input_formats = [DATETIME_INPUT_FORMAT, "%Y-%m-%d %H:%M"]
        self.fields["capacity"].min_value = CAPACITY_MIN
        self.fields["capacity"].max_value = CAPACITY_MAX
        # Розширення від клієнта ігноруємо: формат визначає Pillow за вмістом (clean_cover).
        self.fields["cover"].validators = []

    def clean_title(self):
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("Назва не може бути порожньою.")
        return title

    def clean_description(self):
        return (self.cleaned_data.get("description") or "").strip()

    def clean_starts_at(self):
        starts_at = self.cleaned_data.get("starts_at")
        if starts_at is None:
            return starts_at
        unchanged = (
            self.instance.pk
            and self.instance.starts_at.replace(second=0, microsecond=0)
            == starts_at.replace(second=0, microsecond=0)
        )
        if unchanged:
            # Не змінюємо дату — залишаємо точне збережене значення.
            return self.instance.starts_at
        if starts_at <= timezone.now():
            raise forms.ValidationError("Дата початку має бути в майбутньому.")
        return starts_at

    def clean_capacity(self):
        capacity = self.cleaned_data.get("capacity")
        if capacity is not None and capacity < self.registered_count:
            raise forms.ValidationError(
                f"Не можна зменшити кількість місць нижче кількості записаних ({self.registered_count})."
            )
        return capacity

    def clean_cover(self):
        cover = self.cleaned_data.get("cover")
        if isinstance(cover, UploadedFile):
            ext = validate_cover_image(cover)
            # Оригінальне імʼя ігноруємо; upload_to згенерує covers/<uuid4>.<ext>.
            cover.name = f"cover.{ext}"
        return cover


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["text"]
        labels = {"text": "Коментар"}
        widgets = {
            "text": forms.Textarea(
                attrs={"rows": 3, "maxlength": 2000, "placeholder": "Напишіть коментар…"}
            )
        }

    def clean_text(self):
        text = (self.cleaned_data.get("text") or "").strip()
        if not text:
            raise forms.ValidationError("Коментар не може бути порожнім.")
        return text
