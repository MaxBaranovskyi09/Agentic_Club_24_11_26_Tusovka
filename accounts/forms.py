from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, BaseUserCreationForm

from . import ratelimit
from .models import User, normalize_email

GENERIC_LOGIN_ERROR = "Невірний email або пароль."


class SignupForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ["email", "name"]
        labels = {"email": "Email", "name": "Імʼя"}
        help_texts = {"name": "Так вас бачитимуть інші учасники. До 50 символів."}

    def clean_email(self):
        email = normalize_email(self.cleaned_data.get("email"))
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("Не вдалося зареєструватися з цим email.")
        return email

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Вкажіть імʼя.")
        return name


class EmailAuthenticationForm(AuthenticationForm):
    """Вхід за email з rate limit на email+IP і загальною помилкою."""

    error_messages = {
        "invalid_login": GENERIC_LOGIN_ERROR,
        "inactive": GENERIC_LOGIN_ERROR,
        "rate_limited": "Забагато невдалих спроб входу. Спробуйте за 15 хвилин.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Email"
        self.fields["username"].widget = forms.EmailInput(
            attrs={"autofocus": True, "autocomplete": "email"}
        )

    def clean(self):
        email = normalize_email(self.cleaned_data.get("username"))
        self.cleaned_data["username"] = email
        ip = ratelimit.client_ip(self.request) if self.request else ""
        limit, window = settings.LOGIN_RATE_LIMIT
        if ratelimit.is_limited("login", limit, email, ip):
            raise forms.ValidationError(self.error_messages["rate_limited"], code="rate_limited")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            ratelimit.hit("login", window, email, ip)
            raise
        ratelimit.reset("login", email, ip)
        return cleaned
