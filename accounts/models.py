from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.db import models


def normalize_email(email):
    return (email or "").strip().lower()


def validate_not_blank(value):
    if not (value or "").strip():
        raise ValidationError("Поле не може бути порожнім.")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def get_by_natural_key(self, email):
        return self.get(email=normalize_email(email))

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email обовʼязковий")
        user = self.model(email=normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if not extra_fields.get("is_staff") or not extra_fields.get("is_superuser"):
            raise ValueError("Суперкористувач має мати is_staff=True та is_superuser=True")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField("email", unique=True)
    name = models.CharField("імʼя", max_length=50, validators=[validate_not_blank])

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    objects = UserManager()

    class Meta:
        verbose_name = "користувач"
        verbose_name_plural = "користувачі"

    def clean(self):
        super().clean()
        self.email = normalize_email(self.email)
        self.name = (self.name or "").strip()

    def save(self, *args, **kwargs):
        self.email = normalize_email(self.email)
        self.name = (self.name or "").strip()
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.name

    def __str__(self):
        return self.name
