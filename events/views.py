from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts import ratelimit

from . import services
from .forms import CommentForm, EventForm
from .models import Event, PrivateAccess, Registration
from .permissions import can_edit, get_editable_event, get_viewable_event
from .validators import CONTENT_TYPES

PAGE_SIZE = 20
SEARCH_MAX_LEN = 100


@require_GET
def home(request):
    q = (request.GET.get("q") or "").strip()[:SEARCH_MAX_LEN]
    events = (
        Event.objects.filter(is_private=False, starts_at__gt=timezone.now())
        .select_related("author")
        .order_by("starts_at", "pk")
    )
    context = {"q": q}
    if q:
        events = events.filter(title__icontains=q)
    page = Paginator(events, PAGE_SIZE).get_page(request.GET.get("page"))
    context["page"] = page
    # Лендінг-блоки показуємо лише на першій сторінці без пошуку.
    context["show_landing"] = not q and page.number == 1
    if context["show_landing"]:
        # Береться з того ж запиту (лише публічні майбутні) — приватні сюди не потрапляють.
        featured = events.annotate(taken=Count("registrations")).first()
        if featured:
            context["featured"] = featured
            context["featured_free"] = max(featured.capacity - featured.taken, 0)
    return render(request, "events/home.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def event_create(request):
    if request.method == "POST":
        form = EventForm(request.POST, request.FILES)
        if form.is_valid():
            event = form.save(commit=False)
            event.author = request.user
            event.save()
            messages.success(request, "Подію створено.")
            return redirect("events:detail", public_id=event.public_id)
    else:
        form = EventForm()
    return render(request, "events/event_form.html", {"form": form, "is_create": True})


def _seats(event):
    taken = event.registrations.count()
    return taken, max(event.capacity - taken, 0)


@require_GET
def event_detail(request, public_id):
    event = get_viewable_event(request.user, public_id)
    taken, free = _seats(event)
    is_author = can_edit(request.user, event)
    is_registered = (
        request.user.is_authenticated
        and Registration.objects.filter(event=event, user=request.user).exists()
    )
    context = {
        "event": event,
        "taken": taken,
        "free": free,
        "is_author": is_author,
        "is_registered": is_registered,
        "is_past": event.starts_at <= timezone.now(),
        "comments": event.comments.select_related("author"),
        "comment_form": CommentForm(),
    }
    if is_author:
        context["participants"] = event.registrations.select_related("user")
        if event.is_private:
            context["invite_url"] = request.build_absolute_uri(
                reverse("events:invite", kwargs={"token": event.invite_token})
            )
    return render(request, "events/event_detail.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def event_edit(request, public_id):
    if request.method == "POST":
        with transaction.atomic():
            # Блокування: паралельний запис не проскочить між підрахунком і збереженням.
            event = get_editable_event(request.user, public_id, for_update=True)
            taken = event.registrations.count()
            form = EventForm(
                request.POST, request.FILES, instance=event, registered_count=taken
            )
            if form.is_valid():
                form.save()
                messages.success(request, "Зміни збережено.")
                return redirect("events:detail", public_id=event.public_id)
    else:
        event = get_editable_event(request.user, public_id)
        form = EventForm(instance=event)
    return render(
        request, "events/event_form.html", {"form": form, "event": event, "is_create": False}
    )


@login_required
@require_http_methods(["GET", "POST"])
def event_delete(request, public_id):
    if request.method == "POST":
        with transaction.atomic():
            # Блокуємо подію: паралельний запис не вставить Registration між збором
            # каскадних обʼєктів і DELETE (інакше — порушення FK і 500).
            event = get_editable_event(request.user, public_id, for_update=True)
            event.delete()
        messages.success(request, "Подію видалено.")
        return redirect("events:profile")
    event = get_editable_event(request.user, public_id)
    return render(request, "events/event_confirm_delete.html", {"event": event})


@login_required
@require_POST
def event_register(request, public_id):
    try:
        services.register(request.user, public_id)
        messages.success(request, "Ви записалися на подію. До зустрічі!")
    except services.RegistrationError as exc:
        messages.error(request, str(exc))
    return redirect("events:detail", public_id=public_id)


@login_required
@require_POST
def event_unregister(request, public_id):
    try:
        services.unregister(request.user, public_id)
        messages.info(request, "Запис скасовано.")
    except services.RegistrationError as exc:
        messages.error(request, str(exc))
    return redirect("events:detail", public_id=public_id)


@login_required
@require_POST
def comment_add(request, public_id):
    event = get_viewable_event(request.user, public_id)
    form = CommentForm(request.POST)
    if not form.is_valid():
        for error in form.errors.get("text", []):
            messages.error(request, error)
        return redirect("events:detail", public_id=event.public_id)
    if not ratelimit.throttle("comment", settings.COMMENT_RATE_LIMIT_SECONDS, str(request.user.pk)):
        messages.error(request, "Занадто часто. Зачекайте кілька секунд перед наступним коментарем.")
        return redirect("events:detail", public_id=event.public_id)
    with transaction.atomic():
        # Блокуємо рядок події (і повторно перевіряємо доступ): якщо подію щойно
        # видалили або закрили — 404, а не IntegrityError/500.
        event = get_viewable_event(request.user, public_id, for_update=True)
        comment = form.save(commit=False)
        comment.event = event
        comment.author = request.user
        comment.save()
    messages.success(request, "Коментар додано.")
    return redirect(reverse("events:detail", kwargs={"public_id": event.public_id}) + "#comments")


@login_required
@require_POST
def regenerate_invite(request, public_id):
    event = get_editable_event(request.user, public_id)
    event.regenerate_invite_token()
    messages.success(request, "Інвайт-посилання оновлено. Старе більше не працює.")
    return redirect("events:detail", public_id=event.public_id)


@require_GET
def invite_accept(request, token):
    # Згідно з ТЗ, відкриття посилання видає доступ (операція ідемпотентна).
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    event = get_object_or_404(Event, invite_token=token)
    if event.is_private and event.author_id != request.user.pk:
        try:
            with transaction.atomic():
                _, created = PrivateAccess.objects.get_or_create(user=request.user, event=event)
        except IntegrityError:
            created = False
        if created:
            messages.success(request, "Ви отримали доступ до приватної події.")
    return redirect("events:detail", public_id=event.public_id)


@require_GET
def event_cover(request, public_id):
    event = get_viewable_event(request.user, public_id)
    if not event.cover:
        raise Http404
    ext = event.cover.name.rsplit(".", 1)[-1].lower()
    content_type = CONTENT_TYPES.get(ext)
    if content_type is None:
        raise Http404
    try:
        fh = event.cover.open("rb")
    except FileNotFoundError:
        raise Http404
    response = FileResponse(fh, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, max-age=300" if event.is_private else "public, max-age=3600"
    return response


@login_required
@require_GET
def profile(request):
    created = (
        Event.objects.filter(author=request.user).order_by("-starts_at")
    )
    registered = (
        Event.objects.filter(registrations__user=request.user)
        .select_related("author")
        .order_by("-starts_at")
    )
    return render(
        request,
        "events/profile.html",
        {"created": created, "registered": registered, "now": timezone.now()},
    )
