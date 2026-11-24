from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from . import ratelimit
from .forms import EmailAuthenticationForm, SignupForm


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Вітаємо, {self.request.user.name}!")
        return response


class LogoutView(auth_views.LogoutView):
    """Вбудований LogoutView у Django 5 приймає лише POST (GET → 405)."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "Ви вийшли з акаунта.")
        return response


@require_http_methods(["GET", "POST"])
def signup(request):
    if request.user.is_authenticated:
        return redirect("events:home")
    if request.method == "POST":
        limit, window = settings.SIGNUP_RATE_LIMIT
        ip = ratelimit.client_ip(request)
        if ratelimit.is_limited("signup", limit, ip):
            messages.error(request, "Забагато реєстрацій з вашої адреси. Спробуйте пізніше.")
            return render(request, "registration/signup.html", {"form": SignupForm()}, status=429)
        form = SignupForm(request.POST)
        if form.is_valid():
            ratelimit.hit("signup", window, ip)
            user = form.save()
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, f"Акаунт створено. Ласкаво просимо, {user.name}!")
            return redirect("events:home")
    else:
        form = SignupForm()
    return render(request, "registration/signup.html", {"form": form})
