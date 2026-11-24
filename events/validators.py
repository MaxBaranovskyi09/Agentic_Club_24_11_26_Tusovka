from django.conf import settings
from django.core.exceptions import ValidationError
from PIL import Image, UnidentifiedImageError

# Pillow кидає DecompressionBombError для зображень > 2× цього ліміту ще до декодування.
Image.MAX_IMAGE_PIXELS = settings.COVER_MAX_DIMENSION * settings.COVER_MAX_DIMENSION

# Формат, визначений Pillow за вмістом → (розширення, content-type)
ALLOWED_FORMATS = {
    "JPEG": ("jpg", "image/jpeg"),
    "PNG": ("png", "image/png"),
    "WEBP": ("webp", "image/webp"),
}
CONTENT_TYPES = {ext: ct for ext, ct in ALLOWED_FORMATS.values()}


def validate_cover_image(upload):
    """Перевіряє реальний вміст файлу. Повертає розширення (jpg/png/webp)."""
    max_bytes = settings.COVER_MAX_BYTES
    if upload.size > max_bytes:
        raise ValidationError(f"Файл завеликий. Максимум {max_bytes // (1024 * 1024)} МБ.")
    invalid = ValidationError("Дозволені лише зображення JPEG, PNG або WebP.")
    try:
        upload.seek(0)
        with Image.open(upload) as img:
            fmt = img.format
            width, height = img.size
            if fmt not in ALLOWED_FORMATS:
                raise invalid
            limit = settings.COVER_MAX_DIMENSION
            if width > limit or height > limit:
                raise ValidationError(f"Зображення завелике: максимум {limit}×{limit} пікселів.")
            img.verify()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise invalid
    finally:
        upload.seek(0)
    return ALLOWED_FORMATS[fmt][0]
